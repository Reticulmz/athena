import random
import time
from datetime import UTC, datetime

import pytest
from pydantic import PostgresDsn, RedisDsn

from osu_server.config import AppConfig
from osu_server.domain.chat import (
    ChannelChatDestination,
    ChatAuthorization,
    ChatPersistenceFailureReason,
    ChatSender,
    PrivateChatDestination,
    SendChannelMessageInput,
    SendPrivateMessageInput,
)
from osu_server.domain.chat.channels import Channel, ChannelType
from osu_server.domain.events.channels import ChannelMessageSent, PrivateMessageSent
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.infrastructure.messaging.memory import InMemoryEventBus
from osu_server.infrastructure.state.memory.channel_state_store import (
    InMemoryChannelStateStore,
)
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.bancho_bot.command_service import CommandService
from osu_server.services.bancho_bot.commands import create_builtin_registry
from osu_server.services.chat_service import ChatService
from osu_server.services.commands.chat import (
    PersistChannelMessageUseCase,
    PersistPrivateMessageCommand,
    PersistPrivateMessageUseCase,
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
)
from osu_server.services.queries.chat import (
    ResolveChannelMessageDeliveryQuery,
    ResolvePrivateMessageTargetQuery,
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
    return SendPrivateMessageInput(
        sender=ChatSender(user_id=sender_id, username=sender_name),
        destination=PrivateChatDestination(username=target_name),
        content=content,
    )


@pytest.fixture
def command_state() -> InMemoryCommandRepositoryState:
    return InMemoryCommandRepositoryState()


@pytest.fixture
def uow_factory(command_state: InMemoryCommandRepositoryState) -> InMemoryUnitOfWorkFactory:
    return InMemoryUnitOfWorkFactory(command_state)


@pytest.fixture
def channel_repo(command_state: InMemoryCommandRepositoryState) -> InMemoryChannelRepository:
    return InMemoryChannelRepository(state=command_state)


@pytest.fixture
def channel_state() -> InMemoryChannelStateStore:
    return InMemoryChannelStateStore()


@pytest.fixture
def user_repo(command_state: InMemoryCommandRepositoryState) -> InMemoryUserRepository:
    return InMemoryUserRepository(state=command_state)


@pytest.fixture
async def session_store() -> InMemorySessionStore:
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


@pytest.fixture
def captured_events() -> list[object]:
    return []


@pytest.fixture
def event_bus(captured_events: list[object]) -> InMemoryEventBus:
    bus = InMemoryEventBus()

    async def capture(event: object) -> None:
        captured_events.append(event)

    bus.subscribe(ChannelMessageSent, capture)
    bus.subscribe(PrivateMessageSent, capture)
    return bus


@pytest.fixture
def rate_limiter() -> InMemoryRateLimiter:
    return InMemoryRateLimiter(time_func=lambda: 0.0)


@pytest.fixture
def config() -> AppConfig:
    return AppConfig(
        database_url=PostgresDsn("postgresql+asyncpg://test"),
        valkey_url=RedisDsn("redis://test"),
        message_max_length=50,
        rate_limit_messages=10,
        rate_limit_window=10,
    )


@pytest.fixture
async def channel_delivery_query(
    channel_repo: InMemoryChannelRepository,
    channel_state: InMemoryChannelStateStore,
    uow_factory: InMemoryUnitOfWorkFactory,
) -> ResolveChannelMessageDeliveryQuery:
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
    return ResolvePrivateMessageTargetQuery(
        user_repository=InMemoryUserQueryRepository(uow_factory),
        session_store=session_store,
    )


@pytest.fixture
def command_service() -> CommandService:
    return CommandService(create_builtin_registry())


@pytest.fixture
def chat_service(
    channel_delivery_query: ResolveChannelMessageDeliveryQuery,
    private_message_target_query: ResolvePrivateMessageTargetQuery,
    command_service: CommandService,
    session_store: InMemorySessionStore,
    event_bus: InMemoryEventBus,
    rate_limiter: InMemoryRateLimiter,
    config: AppConfig,
    uow_factory: InMemoryUnitOfWorkFactory,
) -> ChatService:
    send_channel = SendChannelMessageUseCase(
        channel_delivery_query=channel_delivery_query,
        command_service=command_service,
        session_store=session_store,
        event_bus=event_bus,
        rate_limiter=rate_limiter,
        config=config,
    )
    send_private = SendPrivateMessageUseCase(
        target_query=private_message_target_query,
        command_service=command_service,
        session_store=session_store,
        event_bus=event_bus,
        rate_limiter=rate_limiter,
        config=config,
    )
    return ChatService(
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
    chat_service: ChatService,
    command_state: InMemoryCommandRepositoryState,
) -> None:
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
    chat_service: ChatService,
    command_state: InMemoryCommandRepositoryState,
) -> None:
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
    chat_service: ChatService,
    command_state: InMemoryCommandRepositoryState,
) -> None:
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
    chat_service: ChatService,
    captured_events: list[object],
) -> None:
    res = await chat_service.send_channel_message(_channel_message_input())

    assert res is not None
    assert res.delivered_to == {2, 3}
    assert res.content == "hello"
    assert not res.command_responses

    assert len(captured_events) == 1
    event = captured_events[0]
    assert isinstance(event, ChannelMessageSent)
    assert event.content == "hello"
    assert event.sender_id == 1
    assert event.channel_name == "#osu"


@pytest.mark.asyncio
async def test_send_private_message_success(
    chat_service: ChatService,
    user_repo: InMemoryUserRepository,
    session_store: InMemorySessionStore,
    captured_events: list[object],
) -> None:
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
    assert res.target_id == created_target.id
    assert res.is_online is True
    assert res.content == "hello PM"
    assert not res.command_responses

    assert len(captured_events) == 1
    event = captured_events[0]
    assert isinstance(event, PrivateMessageSent)
    assert event.content == "hello PM"
    assert event.sender_id == 1
    assert event.target_id == created_target.id


@pytest.mark.asyncio
async def test_silenced_user_rejected(
    chat_service: ChatService,
    session_store: InMemorySessionStore,
    captured_events: list[object],
) -> None:
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
    assert len(captured_events) == 0


@pytest.mark.asyncio
async def test_rate_limited_rejected(
    chat_service: ChatService,
    rate_limiter: InMemoryRateLimiter,
    config: AppConfig,
    captured_events: list[object],
) -> None:
    # Pre-fill rate limiter to exhaust the limit
    limit = config.rate_limit_messages  # 10
    window = config.rate_limit_window  # 10
    for _ in range(limit):
        _ = await rate_limiter.check(user_id=1, limit=limit, window=window)

    res = await chat_service.send_channel_message(_channel_message_input())
    assert res is None
    assert len(captured_events) == 0


@pytest.mark.asyncio
async def test_channel_delivery_rejected_does_not_fire_event(
    chat_service: ChatService,
    captured_events: list[object],
) -> None:
    res = await chat_service.send_channel_message(_channel_message_input(user_privileges=0))

    assert res is None
    assert len(captured_events) == 0


@pytest.mark.asyncio
async def test_private_target_not_found_does_not_fire_event(
    chat_service: ChatService,
    captured_events: list[object],
) -> None:
    res = await chat_service.send_private_message(_private_message_input(target_name="missing"))

    assert res is not None
    assert res.target_id is None
    assert len(captured_events) == 0


@pytest.mark.asyncio
async def test_empty_message_rejected(
    chat_service: ChatService,
    captured_events: list[object],
) -> None:
    res = await chat_service.send_channel_message(_channel_message_input(content=""))
    assert res is None
    assert len(captured_events) == 0


@pytest.mark.asyncio
async def test_long_message_rejected(
    chat_service: ChatService,
    captured_events: list[object],
) -> None:
    long_msg = "a" * 100
    res = await chat_service.send_channel_message(_channel_message_input(content=long_msg))

    assert res is None
    assert len(captured_events) == 0


@pytest.mark.asyncio
async def test_command_execution(
    chat_service: ChatService,
    captured_events: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mock_randint(_a: int, _b: int) -> int:
        return 50

    monkeypatch.setattr(random, "randint", mock_randint)

    res = await chat_service.send_channel_message(_channel_message_input(content="!roll 100"))

    assert res is not None
    assert res.delivered_to == {2, 3}
    assert len(res.command_responses) > 0
    assert res.command_responses[0].target == "#osu"
    assert res.command_responses[0].content == "sender rolls 50 point(s)"

    # Command messages are also delivered to channel members (Req 8.2)
    assert len(captured_events) == 1
    event = captured_events[0]
    assert isinstance(event, ChannelMessageSent)
    assert event.content == "!roll 100"
    assert event.sender_id == 1
    assert event.channel_name == "#osu"
