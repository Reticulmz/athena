"""Chat command use-case の送信, 永続化, 拒否経路を検証するテスト.

in-memory repository, state store, publisher を使う.
chat transport へ渡す command 結果の契約を検証する.
"""

import random
import time
from datetime import UTC, datetime
from typing import final, override

import pytest
from pydantic import PostgresDsn, RedisDsn

from osu_server.config import AppConfig
from osu_server.domain.chat import (
    ChannelChatDestination,
    ChannelMessageResult,
    ChatAuthorization,
    ChatPersistenceFailureReason,
    ChatPersistenceResult,
    ChatSender,
    PrivateChatDestination,
    PrivateMessageDeliveryStatus,
    PrivateMessageResult,
    SendChannelMessageInput,
    SendPrivateMessageInput,
)
from osu_server.domain.chat.channels import Channel, ChannelType
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.infrastructure.state.memory.channel_state_store import (
    InMemoryChannelStateStore,
)
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter
from osu_server.repositories.memory.commands.channels import InMemoryChannelCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.commands.users import InMemoryUserCommandRepository
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.queries.friends import (
    InMemoryFriendRelationshipQueryRepository,
)
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.chat import (
    ChannelMessagePersistenceWork,
    ChatPersistenceWorkPublisher,
    PersistChannelMessageCommand,
    PersistChannelMessageUseCase,
    PersistPrivateMessageCommand,
    PersistPrivateMessageUseCase,
    PrivateMessagePersistenceWork,
    SendChannelMessageCommand,
    SendChannelMessageUseCase,
    SendPrivateMessageCommand,
    SendPrivateMessageUseCase,
)
from osu_server.services.commands.chat.bancho_bot.command_service import CommandService
from osu_server.services.commands.chat.bancho_bot.commands import create_builtin_registry
from osu_server.services.queries.chat import (
    ResolveChannelMessageDeliveryQuery,
    ResolvePrivateMessageTargetQuery,
)
from osu_server.services.queries.identity.friend_relationships import (
    CheckFriendRelationshipQuery,
)

_NOW = datetime.now(UTC)
_BYPASS_ACL = 1 << 9  # Privileges.BYPASS_CHANNEL_ACL


def _channel_message_input(
    *,
    sender_id: int = 1,
    sender_name: str = "sender",
    channel_name: str = "#osu",
    content: str = "hello",
    user_privileges: int = _BYPASS_ACL,
    user_role_ids: tuple[int, ...] = (),
) -> SendChannelMessageInput:
    """チャネル message 用の command input を既定値から生成する.

    Args:
        sender_id (int): message sender の user ID.
        sender_name (str): sender の表示 username.
        channel_name (str): 送信先チャネル名.
        content (str): 送信する message 本文.
        user_privileges (int): channel ACL 判定に使う privilege bitset.
        user_role_ids (tuple[int, ...]): channel ACL 判定に使う role ID.

    Returns:
        SendChannelMessageInput: command に渡す sender, destination, authorization を持つ input.
    """
    return SendChannelMessageInput(
        sender=ChatSender(user_id=sender_id, username=sender_name),
        destination=ChannelChatDestination(name=channel_name),
        content=content,
        authorization=ChatAuthorization(
            privileges=user_privileges,
            role_ids=user_role_ids,
        ),
    )


def _private_message_input(
    *,
    sender_id: int = 1,
    sender_name: str = "sender",
    target_name: str = "target",
    content: str = "hello PM",
) -> SendPrivateMessageInput:
    """Private message 用の command input を既定値から生成する.

    Args:
        sender_id (int): message sender の user ID.
        sender_name (str): sender の表示 username.
        target_name (str): target の表示 username.
        content (str): 送信する private message 本文.

    Returns:
        SendPrivateMessageInput: command に渡す sender と private destination を持つ input.
    """
    return SendPrivateMessageInput(
        sender=ChatSender(user_id=sender_id, username=sender_name),
        destination=PrivateChatDestination(username=target_name),
        content=content,
    )


@pytest.fixture
def command_state() -> InMemoryCommandRepositoryState:
    """Test ごとに独立した command repository state を提供する.

    Returns:
        InMemoryCommandRepositoryState: user, channel, message を保持する空の state.
    """
    return InMemoryCommandRepositoryState()


@pytest.fixture
def uow_factory(command_state: InMemoryCommandRepositoryState) -> InMemoryUnitOfWorkFactory:
    """Fixture state を共有する UnitOfWork factory を提供する.

    Args:
        command_state (InMemoryCommandRepositoryState): factory が transaction で操作する state.

    Returns:
        InMemoryUnitOfWorkFactory: test 内の command/query repository が共有する factory.
    """
    return InMemoryUnitOfWorkFactory(command_state)


@pytest.fixture
def channel_repo(
    command_state: InMemoryCommandRepositoryState,
) -> InMemoryChannelCommandRepository:
    """Fixture state に書き込む channel command repository を提供する.

    Args:
        command_state (InMemoryCommandRepositoryState): channel を保存する backing state.

    Returns:
        InMemoryChannelCommandRepository: channel seed に使う command repository.
    """
    return InMemoryChannelCommandRepository(command_state)


@pytest.fixture
def channel_state() -> InMemoryChannelStateStore:
    """チャネル member を保持する空の volatile state store を提供する.

    Returns:
        InMemoryChannelStateStore: test 内だけで使用する state store.
    """
    return InMemoryChannelStateStore()


@pytest.fixture
def user_repo(command_state: InMemoryCommandRepositoryState) -> InMemoryUserCommandRepository:
    """Fixture state に書き込む user command repository を提供する.

    Args:
        command_state (InMemoryCommandRepositoryState): user を保存する backing state.

    Returns:
        InMemoryUserCommandRepository: sender と target の seed に使う repository.
    """
    return InMemoryUserCommandRepository(command_state)


@pytest.fixture
async def session_store() -> InMemorySessionStore:
    """Online sender session を持つ in-memory session store を提供する.

    Returns:
        InMemorySessionStore: user ID 1 の active session を持つ store.
    """
    store = InMemorySessionStore()
    await store.create(
        user_id=1,
        token="sender_session",
        data=SessionData(
            user_id=1,
            username="sender",
            privileges=0,
            country="JP",
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            silence_end=0,
        ),
    )
    return store


@final
class FakeChatPersistenceWorkPublisher(ChatPersistenceWorkPublisher):
    """永続化 work を配送せず記録する ChatPersistenceWorkPublisher fake.

    Attributes:
        channel_messages (list[ChannelMessagePersistenceWork]): publish 済み channel work の履歴.
        private_messages (list[PrivateMessagePersistenceWork]): publish 済み private work の履歴.
    """

    def __init__(self) -> None:
        """channel/private message の空の publish 履歴を初期化する."""
        self.channel_messages: list[ChannelMessagePersistenceWork] = []
        self.private_messages: list[PrivateMessagePersistenceWork] = []

    @override
    async def publish_channel_message(
        self,
        work: ChannelMessagePersistenceWork,
    ) -> None:
        """Channel message の永続化 work を履歴へ追加する.

        Args:
            work (ChannelMessagePersistenceWork): publish 要求された channel message work.

        Returns:
            None: work を記録して完了する.
        """
        self.channel_messages.append(work)

    @override
    async def publish_private_message(
        self,
        work: PrivateMessagePersistenceWork,
    ) -> None:
        """Private message の永続化 work を履歴へ追加する.

        Args:
            work (PrivateMessagePersistenceWork): publish 要求された private message work.

        Returns:
            None: work を記録して完了する.
        """
        self.private_messages.append(work)


@pytest.fixture
def persistence_publisher() -> FakeChatPersistenceWorkPublisher:
    """永続化 work の publish 履歴を検証できる fake を提供する.

    Returns:
        FakeChatPersistenceWorkPublisher: 空の work 履歴を持つ publisher.
    """
    return FakeChatPersistenceWorkPublisher()


@pytest.fixture
def rate_limiter() -> InMemoryRateLimiter:
    """固定 clock を使う in-memory rate limiter を提供する.

    Returns:
        InMemoryRateLimiter: test が deterministic に上限へ到達できる limiter.
    """
    return InMemoryRateLimiter(time_func=lambda: 0.0)


@pytest.fixture
def config() -> AppConfig:
    """Chat use-case の message/rate-limit 制約を持つ test config を提供する.

    Returns:
        AppConfig: message length 50 と rate limit 10 を設定した config.
    """
    return AppConfig(
        database_url=PostgresDsn("postgresql+asyncpg://test"),
        valkey_url=RedisDsn("redis://test"),
        message_max_length=50,
        rate_limit_messages=10,
        rate_limit_window=10,
    )


@pytest.fixture
async def channel_delivery_query(
    channel_repo: InMemoryChannelCommandRepository,
    channel_state: InMemoryChannelStateStore,
    uow_factory: InMemoryUnitOfWorkFactory,
) -> ResolveChannelMessageDeliveryQuery:
    """Sender と2人の target member を持つ channel delivery query を提供する.

    Args:
        channel_repo (InMemoryChannelCommandRepository): test channel を保存する repository.
        channel_state (InMemoryChannelStateStore): sender と target member を保存する state store.
        uow_factory (InMemoryUnitOfWorkFactory): query repository が参照する factory.

    Returns:
        ResolveChannelMessageDeliveryQuery: #osu の sender 1 から user 2, 3 へ配信する query.
    """
    channel = Channel(
        id=0,  # auto-assigned by repository
        name="#osu",
        topic="",
        channel_type=ChannelType.PUBLIC,
        auto_join=False,
        rate_limit_messages=None,
        rate_limit_window=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    _ = await channel_repo.create(channel)

    # Sender (1) + delivery targets (2, 3) as channel members
    await channel_state.add_member("#osu", 1)
    await channel_state.add_member("#osu", 2)
    await channel_state.add_member("#osu", 3)

    return ResolveChannelMessageDeliveryQuery(
        channel_repository=InMemoryChannelQueryRepository(uow_factory),
        channel_state=channel_state,
    )


@pytest.fixture
def private_message_target_query(
    uow_factory: InMemoryUnitOfWorkFactory,
    session_store: InMemorySessionStore,
) -> ResolvePrivateMessageTargetQuery:
    """User repository と session store を使う private target query を提供する.

    Args:
        uow_factory (InMemoryUnitOfWorkFactory): user query repository が参照する factory.
        session_store (InMemorySessionStore): target の online 状態を判定する store.

    Returns:
        ResolvePrivateMessageTargetQuery: target user と online 状態を解決する query.
    """
    return ResolvePrivateMessageTargetQuery(
        user_repository=InMemoryUserQueryRepository(uow_factory),
        session_store=session_store,
    )


@pytest.fixture
def command_service() -> CommandService:
    """Builtin BanchoBot command registry を持つ command service を提供する.

    Returns:
        CommandService: !roll などの command を実行する service.
    """
    return CommandService(create_builtin_registry())


@final
class ChatUseCaseHarness:
    """chat use-case を transport 非依存の簡潔な API で呼び出す harness.

    private command wrapper を公開する.
    test が command/result mapping の詳細を重複させないために使用する.

    Attributes:
        _send_channel_msg (SendChannelMessageUseCase): channel message を送信する command.
        _send_private_msg (SendPrivateMessageUseCase): private message を送信する command.
        _persist_channel_msg (PersistChannelMessageUseCase): channel message を永続化する command.
        _persist_private_msg (PersistPrivateMessageUseCase): private message を永続化する command.
    """

    def __init__(
        self,
        *,
        send_channel_message_use_case: SendChannelMessageUseCase,
        send_private_message_use_case: SendPrivateMessageUseCase,
        persist_channel_message_use_case: PersistChannelMessageUseCase,
        persist_private_message_use_case: PersistPrivateMessageUseCase,
    ) -> None:
        """送信と永続化を担当する4つの use-case を設定する.

        Args:
            send_channel_message_use_case (SendChannelMessageUseCase):
                channel message の送信 command.
            send_private_message_use_case (SendPrivateMessageUseCase):
                private message の送信 command.
            persist_channel_message_use_case (PersistChannelMessageUseCase):
                channel message の永続化 command.
            persist_private_message_use_case (PersistPrivateMessageUseCase):
                private message の永続化 command.
        """
        self._send_channel_msg = send_channel_message_use_case
        self._send_private_msg = send_private_message_use_case
        self._persist_channel_msg = persist_channel_message_use_case
        self._persist_private_msg = persist_private_message_use_case

    async def send_channel_message(
        self,
        message: SendChannelMessageInput,
    ) -> ChannelMessageResult | None:
        """Channel message input を command へ変換して送信する.

        Args:
            message (SendChannelMessageInput): 送信する channel message と authorization.

        Returns:
            ChannelMessageResult | None: 許可された message の配信結果. 拒否時は None.
        """
        result = await self._send_channel_msg.execute(SendChannelMessageCommand(message=message))
        return result.result

    async def send_private_message(
        self,
        message: SendPrivateMessageInput,
    ) -> PrivateMessageResult | None:
        """Private message input を command へ変換して送信する.

        Args:
            message (SendPrivateMessageInput): 送信する private message.

        Returns:
            PrivateMessageResult | None: target 解決結果. command が処理不能な場合は None.
        """
        result = await self._send_private_msg.execute(SendPrivateMessageCommand(message=message))
        return result.result

    async def persist_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        """Channel message を durable persistence command へ渡す.

        Args:
            sender_id (int): message sender の user ID.
            channel_name (str): 保存する channel 名.
            content (str): 保存する message 本文.

        Returns:
            ChatPersistenceResult: persistence success または失敗理由.
        """
        return await self._persist_channel_msg.execute(
            PersistChannelMessageCommand(
                sender_id=sender_id,
                channel_name=channel_name,
                content=content,
            )
        )

    async def persist_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult:
        """Private message を durable persistence command へ渡す.

        Args:
            sender_id (int): message sender の user ID.
            target_id (int): message target の user ID.
            content (str): 保存する message 本文.

        Returns:
            ChatPersistenceResult: persistence success または失敗理由.
        """
        return await self._persist_private_msg.execute(
            PersistPrivateMessageCommand(
                sender_id=sender_id,
                target_id=target_id,
                content=content,
            )
        )


@pytest.fixture
def chat_service(
    channel_delivery_query: ResolveChannelMessageDeliveryQuery,
    private_message_target_query: ResolvePrivateMessageTargetQuery,
    command_service: CommandService,
    session_store: InMemorySessionStore,
    persistence_publisher: FakeChatPersistenceWorkPublisher,
    rate_limiter: InMemoryRateLimiter,
    config: AppConfig,
    uow_factory: InMemoryUnitOfWorkFactory,
) -> ChatUseCaseHarness:
    """Chat command use-case を実行可能な dependency graph を構築する.

    Args:
        channel_delivery_query (ResolveChannelMessageDeliveryQuery):
            channel target を解決する query.
        private_message_target_query (ResolvePrivateMessageTargetQuery):
            private target を解決する query.
        command_service (CommandService): BanchoBot command を実行する service.
        session_store (InMemorySessionStore): sender/target session を参照する store.
        persistence_publisher (FakeChatPersistenceWorkPublisher):
            publish work を記録する fake.
        rate_limiter (InMemoryRateLimiter): send rate を制限する limiter.
        config (AppConfig): message 長と rate limit の制約.
        uow_factory (InMemoryUnitOfWorkFactory): persistence/friend query が共有する factory.

    Returns:
        ChatUseCaseHarness: transport を介さず4つの use-case を呼び出す harness.
    """
    send_channel = SendChannelMessageUseCase(
        channel_delivery_query=channel_delivery_query,
        command_service=command_service,
        session_store=session_store,
        persistence_publisher=persistence_publisher,
        rate_limiter=rate_limiter,
        config=config,
    )
    send_private = SendPrivateMessageUseCase(
        target_query=private_message_target_query,
        friend_relationship_query=CheckFriendRelationshipQuery(
            repository=InMemoryFriendRelationshipQueryRepository(uow_factory)
        ),
        command_service=command_service,
        session_store=session_store,
        persistence_publisher=persistence_publisher,
        rate_limiter=rate_limiter,
        config=config,
    )
    return ChatUseCaseHarness(
        send_channel_message_use_case=send_channel,
        send_private_message_use_case=send_private,
        persist_channel_message_use_case=PersistChannelMessageUseCase(
            uow_factory=uow_factory,
        ),
        persist_private_message_use_case=PersistPrivateMessageUseCase(
            uow_factory=uow_factory,
        ),
    )


@pytest.mark.asyncio
async def test_persist_channel_message_writes_through_uow(
    chat_service: ChatUseCaseHarness,
    command_state: InMemoryCommandRepositoryState,
) -> None:
    """Channel message persistence が UnitOfWork 経由で record を作成することを検証する.

    Args:
        chat_service (ChatUseCaseHarness): persistence command を呼び出す harness.
        command_state (InMemoryCommandRepositoryState): 作成済み record を観測する state.

    Returns:
        None: success result と保存済み channel message を検証して完了する.
    """
    result = await chat_service.persist_channel_message(
        sender_id=1,
        channel_name="#osu",
        content="hello",
    )

    assert result.success is True
    assert result.reason is None
    records = list(command_state.channel_messages_by_id.values())
    assert [(record.sender_id, record.channel_name, record.content) for record in records] == [
        (1, "#osu", "hello")
    ]


@pytest.mark.asyncio
async def test_persist_channel_message_returns_uow_repository_failure(
    chat_service: ChatUseCaseHarness,
    command_state: InMemoryCommandRepositoryState,
) -> None:
    """存在しない channel への persistence が repository failure を返すことを検証する.

    Args:
        chat_service (ChatUseCaseHarness): persistence command を呼び出す harness.
        command_state (InMemoryCommandRepositoryState): record 非作成を観測する state.

    Returns:
        None: CHANNEL_NOT_FOUND と空の record state を検証して完了する.
    """
    result = await chat_service.persist_channel_message(
        sender_id=1,
        channel_name="#missing",
        content="hello",
    )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.CHANNEL_NOT_FOUND
    assert command_state.channel_messages_by_id == {}


@pytest.mark.asyncio
async def test_persist_private_message_writes_through_uow(
    chat_service: ChatUseCaseHarness,
    command_state: InMemoryCommandRepositoryState,
) -> None:
    """Private message persistence が UnitOfWork 経由で record を作成することを検証する.

    Args:
        chat_service (ChatUseCaseHarness): persistence command を呼び出す harness.
        command_state (InMemoryCommandRepositoryState): 作成済み record を観測する state.

    Returns:
        None: success result と保存済み private message を検証して完了する.
    """
    result = await chat_service.persist_private_message(
        sender_id=1,
        target_id=2,
        content="secret",
    )

    assert result.success is True
    assert result.reason is None
    records = list(command_state.private_messages_by_id.values())
    assert [(record.sender_id, record.target_id, record.content) for record in records] == [
        (1, 2, "secret")
    ]


@pytest.mark.asyncio
async def test_persist_private_message_without_runtime_returns_failure() -> None:
    """Runtime dependency がない private persistence が明示的に失敗することを検証する.

    Returns:
        None: RUNTIME_UNAVAILABLE failure result を検証して完了する.
    """
    use_case = PersistPrivateMessageUseCase()

    result = await use_case.execute(
        PersistPrivateMessageCommand(
            sender_id=1,
            target_id=2,
            content="secret",
        )
    )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE


@pytest.mark.asyncio
async def test_send_channel_message_success(
    chat_service: ChatUseCaseHarness,
    persistence_publisher: FakeChatPersistenceWorkPublisher,
) -> None:
    """許可済み channel message が target と persistence work を生成することを検証する.

    Args:
        chat_service (ChatUseCaseHarness): send channel command を呼び出す harness.
        persistence_publisher (FakeChatPersistenceWorkPublisher): publish work を観測する fake.

    Returns:
        None: delivery target, content, channel persistence work を検証して完了する.
    """
    res = await chat_service.send_channel_message(_channel_message_input())

    assert res is not None
    assert res.delivered_to == {2, 3}
    assert res.content == "hello"
    assert not res.command_responses

    assert persistence_publisher.channel_messages == [
        ChannelMessagePersistenceWork(
            sender_id=1,
            sender_name="sender",
            channel_name="#osu",
            content="hello",
        )
    ]
    assert persistence_publisher.private_messages == []


@pytest.mark.asyncio
async def test_send_private_message_success(
    chat_service: ChatUseCaseHarness,
    user_repo: InMemoryUserCommandRepository,
    session_store: InMemorySessionStore,
    persistence_publisher: FakeChatPersistenceWorkPublisher,
) -> None:
    """Online private target への message が deliverable として publish されることを検証する.

    Args:
        chat_service (ChatUseCaseHarness): send private command を呼び出す harness.
        user_repo (InMemoryUserCommandRepository): sender/target を seed する repository.
        session_store (InMemorySessionStore): target を online にする store.
        persistence_publisher (FakeChatPersistenceWorkPublisher): publish work を観測する fake.

    Returns:
        None: delivery result と private persistence work を検証して完了する.
    """
    # Seed sender user (consumes id=1) then target user (id=2)
    sender = User(
        id=0,
        username="sender",
        safe_username="sender",
        email="sender@test.local",
        password_hash="hash",
        country="JP",
        created_at=_NOW,
        updated_at=_NOW,
    )
    _ = await user_repo.create(sender)

    target = User(
        id=0,
        username="target",
        safe_username="target",
        email="target@test.local",
        password_hash="hash",
        country="JP",
        created_at=_NOW,
        updated_at=_NOW,
    )
    created_target = await user_repo.create(target)

    # Create session for target so is_online=True
    await session_store.create(
        user_id=created_target.id,
        token="target_session",
        data=SessionData(
            user_id=created_target.id,
            username="target",
            privileges=0,
            country="JP",
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            silence_end=0,
        ),
    )

    res = await chat_service.send_private_message(_private_message_input())

    assert res is not None
    assert res.delivery_status is PrivateMessageDeliveryStatus.DELIVERABLE
    assert res.target_id == created_target.id
    assert res.is_online is True
    assert res.content == "hello PM"
    assert not res.command_responses

    assert persistence_publisher.private_messages == [
        PrivateMessagePersistenceWork(
            sender_id=1,
            sender_name="sender",
            target_id=created_target.id,
            target_name="target",
            content="hello PM",
        )
    ]
    assert persistence_publisher.channel_messages == []


@pytest.mark.asyncio
async def test_friend_only_private_message_blocks_non_friend_without_persistence(
    chat_service: ChatUseCaseHarness,
    user_repo: InMemoryUserCommandRepository,
    session_store: InMemorySessionStore,
    persistence_publisher: FakeChatPersistenceWorkPublisher,
) -> None:
    """friend-only target が非 friend sender の private message を拒否することを検証する.

    Args:
        chat_service (ChatUseCaseHarness): send private command を呼び出す harness.
        user_repo (InMemoryUserCommandRepository): sender/target を seed する repository.
        session_store (InMemorySessionStore): friend-only target を online にする store.
        persistence_publisher (FakeChatPersistenceWorkPublisher):
            private work 非 publish を観測する fake.

    Returns:
        None: BLOCKED_BY_FRIEND_ONLY と空の publish 履歴を検証して完了する.
    """
    sender = await user_repo.create(
        User(
            id=0,
            username="sender",
            safe_username="sender",
            email="sender@test.local",
            password_hash="hash",
            country="JP",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    target = await user_repo.create(
        User(
            id=0,
            username="target",
            safe_username="target",
            email="target@test.local",
            password_hash="hash",
            country="JP",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    await session_store.create(
        user_id=sender.id,
        token="sender_session_actual",
        data=SessionData(
            user_id=sender.id,
            username="sender",
            privileges=0,
            country="JP",
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            silence_end=0,
        ),
    )
    await session_store.create(
        user_id=target.id,
        token="target_session",
        data=SessionData(
            user_id=target.id,
            username="target",
            privileges=0,
            country="JP",
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=True,
            silence_end=0,
        ),
    )

    res = await chat_service.send_private_message(_private_message_input(sender_id=sender.id))

    assert res is not None
    assert res.delivery_status is PrivateMessageDeliveryStatus.BLOCKED_BY_FRIEND_ONLY
    assert res.target_id == target.id
    assert res.is_online is True
    assert persistence_publisher.private_messages == []


@pytest.mark.asyncio
async def test_friend_only_private_message_allows_target_friend(
    chat_service: ChatUseCaseHarness,
    user_repo: InMemoryUserCommandRepository,
    session_store: InMemorySessionStore,
    uow_factory: InMemoryUnitOfWorkFactory,
    persistence_publisher: FakeChatPersistenceWorkPublisher,
) -> None:
    """friend-only target が登録済み friend sender の private message を許可することを検証する.

    Args:
        chat_service (ChatUseCaseHarness): send private command を呼び出す harness.
        user_repo (InMemoryUserCommandRepository): sender/target を seed する repository.
        session_store (InMemorySessionStore): sender/target を online にする store.
        uow_factory (InMemoryUnitOfWorkFactory): friend relationship を追加する factory.
        persistence_publisher (FakeChatPersistenceWorkPublisher):
            publish private work を観測する fake.

    Returns:
        None: DELIVERABLE と target 向け persistence work を検証して完了する.
    """
    sender = await user_repo.create(
        User(
            id=0,
            username="sender",
            safe_username="sender",
            email="sender@test.local",
            password_hash="hash",
            country="JP",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    target = await user_repo.create(
        User(
            id=0,
            username="target",
            safe_username="target",
            email="target@test.local",
            password_hash="hash",
            country="JP",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    async with uow_factory() as uow:
        _ = await uow.friends.add_relationship(target.id, sender.id)
        await uow.commit()
    await session_store.create(
        user_id=sender.id,
        token="sender_session_actual",
        data=SessionData(
            user_id=sender.id,
            username="sender",
            privileges=0,
            country="JP",
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            silence_end=0,
        ),
    )
    await session_store.create(
        user_id=target.id,
        token="target_session",
        data=SessionData(
            user_id=target.id,
            username="target",
            privileges=0,
            country="JP",
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=True,
            silence_end=0,
        ),
    )

    res = await chat_service.send_private_message(_private_message_input(sender_id=sender.id))

    assert res is not None
    assert res.delivery_status is PrivateMessageDeliveryStatus.DELIVERABLE
    assert persistence_publisher.private_messages == [
        PrivateMessagePersistenceWork(
            sender_id=sender.id,
            sender_name="sender",
            target_id=target.id,
            target_name="target",
            content="hello PM",
        )
    ]


@pytest.mark.asyncio
async def test_silenced_user_rejected(
    chat_service: ChatUseCaseHarness,
    session_store: InMemorySessionStore,
    persistence_publisher: FakeChatPersistenceWorkPublisher,
) -> None:
    """Silenced sender の channel message が拒否され work を publish しないことを検証する.

    Args:
        chat_service (ChatUseCaseHarness): send channel command を呼び出す harness.
        session_store (InMemorySessionStore): sender を silenced に差し替える store.
        persistence_publisher (FakeChatPersistenceWorkPublisher):
            publish work 非作成を観測する fake.

    Returns:
        None: None result と空の publish 履歴を検証して完了する.
    """
    # Overwrite sender session with silenced status
    await session_store.create(
        user_id=1,
        token="silenced_session",
        data=SessionData(
            user_id=1,
            username="sender",
            privileges=0,
            country="JP",
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            silence_end=int(time.time()) + 3600,
        ),
    )

    res = await chat_service.send_channel_message(_channel_message_input())
    assert res is None
    assert persistence_publisher.channel_messages == []
    assert persistence_publisher.private_messages == []


@pytest.mark.asyncio
async def test_rate_limited_rejected(
    chat_service: ChatUseCaseHarness,
    rate_limiter: InMemoryRateLimiter,
    config: AppConfig,
    persistence_publisher: FakeChatPersistenceWorkPublisher,
) -> None:
    """Rate limit 上限に達した sender の channel message が拒否されることを検証する.

    Args:
        chat_service (ChatUseCaseHarness): send channel command を呼び出す harness.
        rate_limiter (InMemoryRateLimiter): 上限まで事前消費する limiter.
        config (AppConfig): 消費回数と window を提供する config.
        persistence_publisher (FakeChatPersistenceWorkPublisher):
            publish work 非作成を観測する fake.

    Returns:
        None: None result と空の publish 履歴を検証して完了する.
    """
    # Pre-fill rate limiter to exhaust the limit
    limit = config.rate_limit_messages  # 10
    window = config.rate_limit_window  # 10
    for _ in range(limit):
        _ = await rate_limiter.check(user_id=1, limit=limit, window=window)

    res = await chat_service.send_channel_message(_channel_message_input())
    assert res is None
    assert persistence_publisher.channel_messages == []
    assert persistence_publisher.private_messages == []


@pytest.mark.asyncio
async def test_channel_delivery_rejected_does_not_publish_work(
    chat_service: ChatUseCaseHarness,
    persistence_publisher: FakeChatPersistenceWorkPublisher,
) -> None:
    """Channel delivery query が拒否した message を publish しないことを検証する.

    Args:
        chat_service (ChatUseCaseHarness): privilege を持たない input を送る harness.
        persistence_publisher (FakeChatPersistenceWorkPublisher):
            publish work 非作成を観測する fake.

    Returns:
        None: None result と空の publish 履歴を検証して完了する.
    """
    res = await chat_service.send_channel_message(_channel_message_input(user_privileges=0))

    assert res is None
    assert persistence_publisher.channel_messages == []
    assert persistence_publisher.private_messages == []


@pytest.mark.asyncio
async def test_private_target_not_found_does_not_publish_work(
    chat_service: ChatUseCaseHarness,
    persistence_publisher: FakeChatPersistenceWorkPublisher,
) -> None:
    """Missing private target が persistence work を publish しないことを検証する.

    Args:
        chat_service (ChatUseCaseHarness): missing target へ送信する harness.
        persistence_publisher (FakeChatPersistenceWorkPublisher):
            publish work 非作成を観測する fake.

    Returns:
        None: TARGET_NOT_FOUND と空の publish 履歴を検証して完了する.
    """
    res = await chat_service.send_private_message(_private_message_input(target_name="missing"))

    assert res is not None
    assert res.delivery_status is PrivateMessageDeliveryStatus.TARGET_NOT_FOUND
    assert res.target_id is None
    assert persistence_publisher.channel_messages == []
    assert persistence_publisher.private_messages == []


@pytest.mark.asyncio
async def test_empty_message_rejected(
    chat_service: ChatUseCaseHarness,
    persistence_publisher: FakeChatPersistenceWorkPublisher,
) -> None:
    """空の channel message が validation で拒否されることを検証する.

    Args:
        chat_service (ChatUseCaseHarness): 空 content を送信する harness.
        persistence_publisher (FakeChatPersistenceWorkPublisher):
            publish work 非作成を観測する fake.

    Returns:
        None: None result と空の publish 履歴を検証して完了する.
    """
    res = await chat_service.send_channel_message(_channel_message_input(content=""))
    assert res is None
    assert persistence_publisher.channel_messages == []
    assert persistence_publisher.private_messages == []


@pytest.mark.asyncio
async def test_long_message_rejected(
    chat_service: ChatUseCaseHarness,
    persistence_publisher: FakeChatPersistenceWorkPublisher,
) -> None:
    """Config の最大長を超える channel message が拒否されることを検証する.

    Args:
        chat_service (ChatUseCaseHarness): 長すぎる content を送信する harness.
        persistence_publisher (FakeChatPersistenceWorkPublisher):
            publish work 非作成を観測する fake.

    Returns:
        None: None result と空の publish 履歴を検証して完了する.
    """
    long_msg = "a" * 100
    res = await chat_service.send_channel_message(_channel_message_input(content=long_msg))

    assert res is None
    assert persistence_publisher.channel_messages == []
    assert persistence_publisher.private_messages == []


@pytest.mark.asyncio
async def test_command_execution(
    chat_service: ChatUseCaseHarness,
    persistence_publisher: FakeChatPersistenceWorkPublisher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BanchoBot command が response と元 message の persistence work を生成することを検証する.

    Args:
        chat_service (ChatUseCaseHarness): !roll command を送信する harness.
        persistence_publisher (FakeChatPersistenceWorkPublisher):
            publish channel work を観測する fake.
        monkeypatch (pytest.MonkeyPatch): random result を deterministic にする fixture.

    Returns:
        None: command response, delivery target, persistence work を検証して完了する.
    """

    def mock_randint(_a: int, _b: int) -> int:
        """!roll command の乱数結果を固定値にする fake.

        Args:
            _a (int): random range の下限. 使用しない.
            _b (int): random range の上限. 使用しない.

        Returns:
            int: 常に 50.
        """
        return 50

    monkeypatch.setattr(random, "randint", mock_randint)

    res = await chat_service.send_channel_message(_channel_message_input(content="!roll 100"))

    assert res is not None
    assert res.delivered_to == {2, 3}
    assert len(res.command_responses) > 0
    assert res.command_responses[0].target == "#osu"
    assert res.command_responses[0].content == "sender rolls 50 point(s)"

    assert persistence_publisher.channel_messages == [
        ChannelMessagePersistenceWork(
            sender_id=1,
            sender_name="sender",
            channel_name="#osu",
            content="!roll 100",
        )
    ]
    assert persistence_publisher.private_messages == []
