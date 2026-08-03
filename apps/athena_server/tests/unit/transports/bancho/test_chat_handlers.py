"""ChatHandlersがC2S payloadをchat commandへ変換しsession認可を使うことを検証する."""

from __future__ import annotations

import pytest

from osu_server.domain.chat import (
    ChannelMessageResult,
    ChatCommandResponse,
    PrivateMessageDeliveryStatus,
    PrivateMessageResult,
)
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.services.commands.chat import (
    JoinChannelCommand,
    JoinChannelResult,
    LeaveChannelCommand,
    SendChannelMessageCommand,
    SendChannelMessageResult,
    SendPrivateMessageCommand,
    SendPrivateMessageResult,
)
from osu_server.transports.stable.bancho.handlers.chat import ChatHandlers
from osu_server.transports.stable.bancho.protocol.c2s import (
    channel_name_payload,
    message_payload,
)
from osu_server.transports.stable.bancho.protocol.s2c.chat import send_message, user_dm_blocked

# ── Stubs ────────────────────────────────────────────────────────────────


class StubSendChannelMessageUseCase:
    """Channel message commandを記録して設定済みresultを返すtest stub.

    Attributes:
        calls (list[dict[str, object]]): commandから抽出したfieldの呼出順list.
        channel_result (ChannelMessageResult | None): executeが返すchannel message result.
    """

    def __init__(self) -> None:
        """既定のdelivered resultと空の呼出し記録でstubを初期化する."""
        self.calls: list[dict[str, object]] = []
        self.channel_result: ChannelMessageResult | None = ChannelMessageResult(
            delivered_to={2, 3}, content="hello", command_responses=()
        )

    async def execute(
        self,
        command: SendChannelMessageCommand,
    ) -> SendChannelMessageResult:
        """Channel message commandのfieldを記録して設定済みresultを返す.

        Args:
            command (SendChannelMessageCommand): handlerが構築したchannel message command.

        Returns:
            SendChannelMessageResult: channel_resultを包むuse-case result.
        """
        message = command.message
        self.calls.append(
            {
                "method": "send_channel_message",
                "sender_id": message.sender.user_id,
                "sender_name": message.sender.username,
                "channel_name": message.destination.name,
                "content": message.content,
                "user_privileges": message.authorization.privileges,
                "user_role_ids": message.authorization.role_ids,
            }
        )
        return SendChannelMessageResult(result=self.channel_result)


class StubSendPrivateMessageUseCase:
    """Private message commandを記録して設定済みresultを返すtest stub.

    Attributes:
        calls (list[dict[str, object]]): commandから抽出したfieldの呼出順list.
        private_result (PrivateMessageResult | None): executeが返すprivate message result.
    """

    def __init__(self) -> None:
        """既定のonline delivery resultと空の呼出し記録でstubを初期化する."""
        self.calls: list[dict[str, object]] = []
        self.private_result: PrivateMessageResult | None = PrivateMessageResult(
            target_id=2, is_online=True, content="secret", command_responses=()
        )

    async def execute(
        self,
        command: SendPrivateMessageCommand,
    ) -> SendPrivateMessageResult:
        """Private message commandのfieldを記録して設定済みresultを返す.

        Args:
            command (SendPrivateMessageCommand): handlerが構築したprivate message command.

        Returns:
            SendPrivateMessageResult: private_resultを包むuse-case result.
        """
        message = command.message
        self.calls.append(
            {
                "method": "send_private_message",
                "sender_id": message.sender.user_id,
                "sender_name": message.sender.username,
                "target_name": message.destination.username,
                "content": message.content,
            }
        )
        return SendPrivateMessageResult(result=self.private_result)


class StubJoinChannelUseCase:
    """Join channel commandを記録して成功を返すtest stub.

    Attributes:
        calls (list[dict[str, object]]): commandから抽出したfieldの呼出順list.
    """

    def __init__(self) -> None:
        """空のcommand記録を持つstubを初期化する."""
        self.calls: list[dict[str, object]] = []

    async def execute(
        self,
        command: JoinChannelCommand,
    ) -> JoinChannelResult:
        """Join channel commandを記録してjoined resultを返す.

        Args:
            command (JoinChannelCommand): handlerが構築したchannel join command.

        Returns:
            JoinChannelResult: joinedがTrueの成功result.
        """
        self.calls.append(
            {
                "method": "join",
                "user_id": command.user_id,
                "user_privileges": command.user_privileges,
                "user_role_ids": command.user_role_ids,
                "channel_name": command.channel_name,
            }
        )
        return JoinChannelResult(joined=True)


class StubLeaveChannelUseCase:
    """Leave channel commandを記録するtest stub.

    Attributes:
        calls (list[dict[str, object]]): commandから抽出したfieldの呼出順list.
    """

    def __init__(self) -> None:
        """空のcommand記録を持つstubを初期化する."""
        self.calls: list[dict[str, object]] = []

    async def execute(
        self,
        command: LeaveChannelCommand,
    ) -> None:
        """Leave channel commandのfieldを記録する.

        Args:
            command (LeaveChannelCommand): handlerが構築したchannel leave command.

        Returns:
            None: commandのfieldを呼出し記録へ追加して完了する.
        """
        self.calls.append(
            {
                "method": "leave",
                "user_id": command.user_id,
                "channel_name": command.channel_name,
            }
        )


class StubSessionStore:
    """指定userに固定sessionを返すSessionStore test stub.

    Attributes:
        session (SessionData | None): get_by_userが返すcurrent session. Noneなら未ログインを表す.
    """

    session: SessionData | None

    def __init__(self, session: SessionData | None = None) -> None:
        """指定sessionまたは既定のauthorized sessionでstubを初期化する.

        Args:
            session (SessionData | None): get_by_userで返すsession. None時は既定sessionを生成する.
        """
        self.session = session or SessionData(
            user_id=1,
            username="test_user",
            privileges=0,
            country="JP",
            osu_version="b20260101",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
        )

    async def get_by_user(self, _user_id: int) -> SessionData | None:
        """指定user IDにかかわらず設定済みsessionを返す.

        Args:
            _user_id (int): sessionを検索するstable user ID. stubでは使用しない.

        Returns:
            SessionData | None: 設定済みsession. Noneならsession未発見を表す.
        """
        return self.session


# ── Helpers ──────────────────────────────────────────────────────────────


def _build_message_payload(
    sender: str = "test_user",
    content: str = "hello",
    target: str = "#osu",
    sender_id: int = 1,
) -> bytes:
    """Channelまたはprivate message用のserialized payloadを構築する.

    Args:
        sender (str): payloadへ設定する送信者名.
        content (str): payloadへ設定するmessage本文.
        target (str): payloadへ設定するchannel名またはtarget user名.
        sender_id (int): payloadへ設定する送信者stable user ID.

    Returns:
        bytes: C2S message protocol definitionでserializeしたpayload.
    """
    return message_payload(
        sender=sender,
        content=content,
        target=target,
        sender_id=sender_id,
    )


def _build_banchostring_payload(value: str) -> bytes:
    """Joinまたはleave channel用のBanchoString payloadを構築する.

    Args:
        value (str): payloadへ設定するchannel名.

    Returns:
        bytes: C2S channel name protocol definitionでserializeしたpayload.
    """
    return channel_name_payload(value)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def send_channel_message() -> StubSendChannelMessageUseCase:
    """Channel message commandを記録するstubを提供する.

    Returns:
        StubSendChannelMessageUseCase: testごとに独立したchannel message use-case stub.
    """
    return StubSendChannelMessageUseCase()


@pytest.fixture
def send_private_message() -> StubSendPrivateMessageUseCase:
    """Private message commandを記録するstubを提供する.

    Returns:
        StubSendPrivateMessageUseCase: testごとに独立したprivate message use-case stub.
    """
    return StubSendPrivateMessageUseCase()


@pytest.fixture
def join_channel() -> StubJoinChannelUseCase:
    """Join channel commandを記録するstubを提供する.

    Returns:
        StubJoinChannelUseCase: testごとに独立したjoin channel use-case stub.
    """
    return StubJoinChannelUseCase()


@pytest.fixture
def leave_channel() -> StubLeaveChannelUseCase:
    """Leave channel commandを記録するstubを提供する.

    Returns:
        StubLeaveChannelUseCase: testごとに独立したleave channel use-case stub.
    """
    return StubLeaveChannelUseCase()


@pytest.fixture
def session_store() -> StubSessionStore:
    """既定のauthorized sessionを返すstore stubを提供する.

    Returns:
        StubSessionStore: testごとに独立したsession store stub.
    """
    return StubSessionStore()


@pytest.fixture
def packet_queue() -> InMemoryPacketQueue:
    """Stable response packetを観測できるin-memory queueを提供する.

    Returns:
        InMemoryPacketQueue: testごとに独立したpacket queue.
    """
    return InMemoryPacketQueue()


@pytest.fixture
def handlers(
    send_channel_message: StubSendChannelMessageUseCase,
    send_private_message: StubSendPrivateMessageUseCase,
    join_channel: StubJoinChannelUseCase,
    leave_channel: StubLeaveChannelUseCase,
    session_store: StubSessionStore,
    packet_queue: InMemoryPacketQueue,
) -> ChatHandlers:
    """Fixture stubを注入したChatHandlersを構築する.

    Args:
        send_channel_message (StubSendChannelMessageUseCase): channel message用stub.
        send_private_message (StubSendPrivateMessageUseCase): private message用stub.
        join_channel (StubJoinChannelUseCase): channel join用stub.
        leave_channel (StubLeaveChannelUseCase): channel leave用stub.
        session_store (StubSessionStore): current sessionを返すstore stub.
        packet_queue (InMemoryPacketQueue): handler responseを観測するqueue.

    Returns:
        ChatHandlers: chat commandとsession dependencyを持つhandler集合.
    """
    return ChatHandlers(
        send_channel_message=send_channel_message,  # pyright: ignore[reportArgumentType]
        send_private_message=send_private_message,  # pyright: ignore[reportArgumentType]
        join_channel=join_channel,  # pyright: ignore[reportArgumentType]
        leave_channel=leave_channel,  # pyright: ignore[reportArgumentType]
        session_store=session_store,  # pyright: ignore[reportArgumentType]
        packet_queue=packet_queue,
    )


async def test_malformed_chat_payloads_are_dropped_without_use_case_calls(
    handlers: ChatHandlers,
    send_channel_message: StubSendChannelMessageUseCase,
    send_private_message: StubSendPrivateMessageUseCase,
    join_channel: StubJoinChannelUseCase,
    leave_channel: StubLeaveChannelUseCase,
) -> None:
    """Malformed chat payloadがいずれのuse caseも呼ばないことを検証する.

    Args:
        handlers (ChatHandlers): malformed payloadを処理するhandler集合.
        send_channel_message (StubSendChannelMessageUseCase): channel command記録を観測するstub.
        send_private_message (StubSendPrivateMessageUseCase): private command記録を観測するstub.
        join_channel (StubJoinChannelUseCase): join command記録を観測するstub.
        leave_channel (StubLeaveChannelUseCase): leave command記録を観測するstub.

    Returns:
        None: 4種のstubが空の呼出し記録を保つことを確認して完了する.
    """
    await handlers.handle_send_message(b"\x00\x00", user_id=1)
    await handlers.handle_send_private_message(b"\x00\x00", user_id=1)
    await handlers.handle_join_channel(b"\x0c", user_id=1)
    await handlers.handle_leave_channel(b"\x0c", user_id=1)

    assert send_channel_message.calls == []
    assert send_private_message.calls == []
    assert join_channel.calls == []
    assert leave_channel.calls == []


# ── handle_send_message ──────────────────────────────────────────────────


class TestSendMessage:
    """Channel message handlerのpayload変換とsession認可伝播を検証する."""

    async def test_parses_message_and_calls_send_channel_message(
        self,
        handlers: ChatHandlers,
        send_channel_message: StubSendChannelMessageUseCase,
        session_store: StubSessionStore,  # pyright: ignore[reportUnusedParameter]  # noqa: ARG002
    ) -> None:
        """Message payloadのfieldをchannel commandへ変換することを検証する.

        Args:
            handlers (ChatHandlers): channel messageを処理するhandler集合.
            send_channel_message (StubSendChannelMessageUseCase): command fieldを記録するstub.
            session_store (StubSessionStore): 既定sessionを提供するfixture.

        Returns:
            None: sender, channel, content, session認可を持つcommand記録を確認して完了する.
        """
        payload = _build_message_payload(
            sender="test_user", content="hello", target="#osu", sender_id=1
        )

        await handlers.handle_send_message(payload, user_id=1)

        assert len(send_channel_message.calls) == 1
        call = send_channel_message.calls[0]
        assert call["method"] == "send_channel_message"
        assert call["sender_id"] == 1
        assert call["sender_name"] == "test_user"
        assert call["channel_name"] == "#osu"
        assert call["content"] == "hello"
        assert call["user_privileges"] == 0
        assert call["user_role_ids"] == ()

    async def test_passes_authorization_from_session(
        self,
        handlers: ChatHandlers,
        send_channel_message: StubSendChannelMessageUseCase,
        session_store: StubSessionStore,
    ) -> None:
        """Action時点のsession privilegesとrole IDsをchannel commandへ渡すことを検証する.

        Args:
            handlers (ChatHandlers): channel messageを処理するhandler集合.
            send_channel_message (StubSendChannelMessageUseCase): command fieldを記録するstub.
            session_store (StubSessionStore): 認可値を差し替えるsession store stub.

        Returns:
            None: 更新したprivilegesとrole IDsを持つcommand記録を確認して完了する.
        """
        session_store.session = SessionData(
            user_id=1,
            username="test_user",
            privileges=8,
            country="JP",
            osu_version="b20260101",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            role_ids=(1, 2),
        )
        payload = _build_message_payload()

        await handlers.handle_send_message(payload, user_id=1)

        assert send_channel_message.calls[0]["user_privileges"] == 8
        assert send_channel_message.calls[0]["user_role_ids"] == (1, 2)

    async def test_sender_only_command_response_not_sent_to_channel_members(
        self,
        handlers: ChatHandlers,
        send_channel_message: StubSendChannelMessageUseCase,
        packet_queue: InMemoryPacketQueue,
        session_store: StubSessionStore,  # pyright: ignore[reportUnusedParameter]  # noqa: ARG002
    ) -> None:
        """Channel commandのprivate guidanceがsenderだけへ配送されることを検証する.

        Args:
            handlers (ChatHandlers): channel messageを処理するhandler集合.
            send_channel_message (StubSendChannelMessageUseCase): command responseを返すstub.
            packet_queue (InMemoryPacketQueue): recipientごとのpacketを観測するqueue.
            session_store (StubSessionStore): senderとrecipientのsessionを有効化するfixture.

        Returns:
            None: channel responseはmemberへ送りprivate guidanceはsenderだけへ送ることを
            確認して完了する.
        """
        await packet_queue.refresh_ttl(1, ttl=60)
        await packet_queue.refresh_ttl(2, ttl=60)
        await packet_queue.refresh_ttl(3, ttl=60)
        send_channel_message.channel_result = ChannelMessageResult(
            delivered_to={2, 3},
            content="!ban user",
            command_responses=(
                ChatCommandResponse(
                    target="#osu",
                    content="Unknown command. Type !help for available commands.",
                ),
                ChatCommandResponse(
                    target="test_user",
                    content="The !ban command can only be used in pm.",
                ),
            ),
        )
        payload = _build_message_payload(content="!ban user", target="#osu")

        await handlers.handle_send_message(payload, user_id=1)

        user_message = send_message(
            sender="test_user",
            content="!ban user",
            target="#osu",
            sender_id=1,
        )
        unknown_packet = send_message(
            sender=BANCHO_BOT_IDENTITY.username,
            content="Unknown command. Type !help for available commands.",
            target="#osu",
            sender_id=BANCHO_BOT_IDENTITY.user_id,
        )
        guidance_packet = send_message(
            sender=BANCHO_BOT_IDENTITY.username,
            content="The !ban command can only be used in pm.",
            target="test_user",
            sender_id=BANCHO_BOT_IDENTITY.user_id,
        )

        assert await packet_queue.dequeue_all(2) == user_message + unknown_packet
        assert await packet_queue.dequeue_all(3) == user_message + unknown_packet
        assert await packet_queue.dequeue_all(1) == unknown_packet + guidance_packet

    async def test_session_not_found_does_nothing(
        self,
        send_channel_message: StubSendChannelMessageUseCase,
        send_private_message: StubSendPrivateMessageUseCase,
        join_channel: StubJoinChannelUseCase,
        leave_channel: StubLeaveChannelUseCase,
        session_store: StubSessionStore,
        packet_queue: InMemoryPacketQueue,
    ) -> None:
        """Session未発見のchannel messageがuse caseを呼ばないことを検証する.

        Args:
            send_channel_message (StubSendChannelMessageUseCase): channel command記録を
            観測するstub.
            send_private_message (StubSendPrivateMessageUseCase): private dependencyを満たすstub.
            join_channel (StubJoinChannelUseCase): join dependencyを満たすstub.
            leave_channel (StubLeaveChannelUseCase): leave dependencyを満たすstub.
            session_store (StubSessionStore): Noneを返すよう設定するstore stub.
            packet_queue (InMemoryPacketQueue): handler作成に必要なqueue.

        Returns:
            None: channel command記録が空であることを確認して完了する.
        """
        session_store.session = None
        handlers = ChatHandlers(
            send_channel_message=send_channel_message,  # pyright: ignore[reportArgumentType]
            send_private_message=send_private_message,  # pyright: ignore[reportArgumentType]
            join_channel=join_channel,  # pyright: ignore[reportArgumentType]
            leave_channel=leave_channel,  # pyright: ignore[reportArgumentType]
            session_store=session_store,  # pyright: ignore[reportArgumentType]
            packet_queue=packet_queue,
        )

        payload = _build_message_payload()

        await handlers.handle_send_message(payload, user_id=999)

        assert len(send_channel_message.calls) == 0


# ── handle_send_private_message ──────────────────────────────────────────


class TestSendPrivateMessage:
    """Private message handlerのpayload変換とdelivery failure packetを検証する."""

    async def test_parses_message_and_calls_send_private_message(
        self,
        handlers: ChatHandlers,
        send_private_message: StubSendPrivateMessageUseCase,
        session_store: StubSessionStore,  # pyright: ignore[reportUnusedParameter]  # noqa: ARG002
    ) -> None:
        """Message payloadのfieldをprivate message commandへ変換することを検証する.

        Args:
            handlers (ChatHandlers): private messageを処理するhandler集合.
            send_private_message (StubSendPrivateMessageUseCase): command fieldを記録するstub.
            session_store (StubSessionStore): 既定sessionを提供するfixture.

        Returns:
            None: sender, target, contentを持つprivate command記録を確認して完了する.
        """
        payload = _build_message_payload(
            sender="test_user", content="secret", target="target", sender_id=1
        )

        await handlers.handle_send_private_message(payload, user_id=1)

        assert len(send_private_message.calls) == 1
        call = send_private_message.calls[0]
        assert call["method"] == "send_private_message"
        assert call["sender_id"] == 1
        assert call["sender_name"] == "test_user"
        assert call["target_name"] == "target"
        assert call["content"] == "secret"

    async def test_session_not_found_does_nothing(
        self,
        handlers: ChatHandlers,
        send_private_message: StubSendPrivateMessageUseCase,
        session_store: StubSessionStore,
    ) -> None:
        """Session未発見のprivate messageがuse caseを呼ばないことを検証する.

        Args:
            handlers (ChatHandlers): private messageを処理するhandler集合.
            send_private_message (StubSendPrivateMessageUseCase): command記録を観測するstub.
            session_store (StubSessionStore): Noneを返すよう設定するstore stub.

        Returns:
            None: private command記録が空であることを確認して完了する.
        """
        session_store.session = None

        payload = _build_message_payload()

        await handlers.handle_send_private_message(payload, user_id=999)

        assert len(send_private_message.calls) == 0

    async def test_blocked_private_message_enqueues_user_dm_blocked_to_sender(
        self,
        handlers: ChatHandlers,
        send_private_message: StubSendPrivateMessageUseCase,
        packet_queue: InMemoryPacketQueue,
        session_store: StubSessionStore,  # pyright: ignore[reportUnusedParameter]  # noqa: ARG002
    ) -> None:
        """Friend only block時にsenderへuser_dm_blockedだけを送ることを検証する.

        Args:
            handlers (ChatHandlers): private messageを処理するhandler集合.
            send_private_message (StubSendPrivateMessageUseCase): block delivery resultを返すstub.
            packet_queue (InMemoryPacketQueue): senderとtargetのpacketを観測するqueue.
            session_store (StubSessionStore): senderとtargetのsessionを有効化するfixture.

        Returns:
            None: senderだけがblocked packetを受けtarget queueは空であることを確認して完了する.
        """
        await packet_queue.refresh_ttl(1, ttl=60)
        await packet_queue.refresh_ttl(2, ttl=60)
        send_private_message.private_result = PrivateMessageResult(
            target_id=2,
            is_online=True,
            content="secret",
            command_responses=(),
            delivery_status=PrivateMessageDeliveryStatus.BLOCKED_BY_FRIEND_ONLY,
        )
        payload = _build_message_payload(
            sender="test_user",
            content="secret",
            target="target",
            sender_id=1,
        )

        await handlers.handle_send_private_message(payload, user_id=1)

        assert await packet_queue.dequeue_all(1) == user_dm_blocked(target="target")
        assert await packet_queue.dequeue_all(2) == b""


# ── handle_join_channel ──────────────────────────────────────────────────


class TestJoinChannel:
    """Join channel handlerがBanchoStringとsession認可をcommandへ変換することを検証する."""

    async def test_parses_channel_name_and_calls_join(
        self,
        handlers: ChatHandlers,
        join_channel: StubJoinChannelUseCase,
        session_store: StubSessionStore,
    ) -> None:
        """Channel nameとsession認可をjoin commandへ変換することを検証する.

        Args:
            handlers (ChatHandlers): join requestを処理するhandler集合.
            join_channel (StubJoinChannelUseCase): join command fieldを記録するstub.
            session_store (StubSessionStore): 認可値を差し替えるsession store stub.

        Returns:
            None: channel名とsession privilegesおよびrole IDsを確認して完了する.
        """
        session_store.session = SessionData(
            user_id=1,
            username="test_user",
            privileges=8,
            country="JP",
            osu_version="b20260101",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            role_ids=(1, 2),
        )
        payload = _build_banchostring_payload("#osu")

        await handlers.handle_join_channel(payload, user_id=1)

        assert len(join_channel.calls) == 1
        call = join_channel.calls[0]
        assert call["method"] == "join"
        assert call["user_id"] == 1
        assert call["channel_name"] == "#osu"
        assert call["user_privileges"] == 8
        assert call["user_role_ids"] == (1, 2)

    async def test_session_not_found_does_nothing(
        self,
        handlers: ChatHandlers,
        join_channel: StubJoinChannelUseCase,
        session_store: StubSessionStore,
    ) -> None:
        """Session未発見のjoin requestがuse caseを呼ばないことを検証する.

        Args:
            handlers (ChatHandlers): join requestを処理するhandler集合.
            join_channel (StubJoinChannelUseCase): command記録を観測するstub.
            session_store (StubSessionStore): Noneを返すよう設定するstore stub.

        Returns:
            None: join command記録が空であることを確認して完了する.
        """
        session_store.session = None

        payload = _build_banchostring_payload("#osu")

        await handlers.handle_join_channel(payload, user_id=999)

        assert len(join_channel.calls) == 0


# ── authorization refresh observation ──────────────────────────────────────


class TestAuthorizationRefreshObservation:
    """Handlerがlogin時のcacheではなくaction時のsession認可を読むことを検証する."""

    async def test_updated_session_authorization_reflected_in_next_action(
        self,
        send_channel_message: StubSendChannelMessageUseCase,
        send_private_message: StubSendPrivateMessageUseCase,
        join_channel: StubJoinChannelUseCase,
        leave_channel: StubLeaveChannelUseCase,
        packet_queue: InMemoryPacketQueue,
    ) -> None:
        """Session認可の更新が次のC2S actionへ反映されることを検証する.

        Args:
            send_channel_message (StubSendChannelMessageUseCase): authorization fieldを
            記録するstub.
            send_private_message (StubSendPrivateMessageUseCase): handler作成に必要なprivate stub.
            join_channel (StubJoinChannelUseCase): handler作成に必要なjoin stub.
            leave_channel (StubLeaveChannelUseCase): handler作成に必要なleave stub.
            packet_queue (InMemoryPacketQueue): handler作成に必要なqueue.

        Returns:
            None: refresh前後のactionがそれぞれ対応するprivilegesとrole IDsを使うことを
            確認して完了する.
        """
        store = StubSessionStore(
            session=SessionData(
                user_id=1,
                username="test_user",
                privileges=4,  # initial
                country="JP",
                osu_version="b20260101",
                utc_offset=9,
                display_city=False,
                client_hashes="",
                pm_private=False,
                role_ids=(1,),
            )
        )
        handlers = ChatHandlers(
            send_channel_message=send_channel_message,  # pyright: ignore[reportArgumentType]
            send_private_message=send_private_message,  # pyright: ignore[reportArgumentType]
            join_channel=join_channel,  # pyright: ignore[reportArgumentType]
            leave_channel=leave_channel,  # pyright: ignore[reportArgumentType]
            session_store=store,  # pyright: ignore[reportArgumentType]
            packet_queue=packet_queue,
        )

        # First action: initial authorization
        await handlers.handle_send_message(_build_message_payload(), user_id=1)
        assert send_channel_message.calls[0]["user_privileges"] == 4
        assert send_channel_message.calls[0]["user_role_ids"] == (1,)

        # Simulate authorization refresh: role grant adds ADMIN privilege + new role
        store.session = SessionData(
            user_id=1,
            username="test_user",
            privileges=260,  # updated (e.g. NORMAL | ADMIN)
            country="JP",
            osu_version="b20260101",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            role_ids=(1, 4),
        )

        # Second action: sees updated authorization without re-login
        await handlers.handle_send_message(_build_message_payload(), user_id=1)
        assert send_channel_message.calls[1]["user_privileges"] == 260
        assert send_channel_message.calls[1]["user_role_ids"] == (1, 4)


# ── handle_leave_channel ─────────────────────────────────────────────────


class TestLeaveChannel:
    """Leave channel handlerがBanchoStringをleave commandへ変換することを検証する."""

    async def test_parses_channel_name_and_calls_leave(
        self,
        handlers: ChatHandlers,
        leave_channel: StubLeaveChannelUseCase,
        session_store: StubSessionStore,  # pyright: ignore[reportUnusedParameter]  # noqa: ARG002
    ) -> None:
        """Channel nameをleave commandへ変換することを検証する.

        Args:
            handlers (ChatHandlers): leave requestを処理するhandler集合.
            leave_channel (StubLeaveChannelUseCase): leave command fieldを記録するstub.
            session_store (StubSessionStore): 既定sessionを提供するfixture.

        Returns:
            None: user IDとchannel名を持つleave command記録を確認して完了する.
        """
        payload = _build_banchostring_payload("#osu")

        await handlers.handle_leave_channel(payload, user_id=1)

        assert len(leave_channel.calls) == 1
        call = leave_channel.calls[0]
        assert call["method"] == "leave"
        assert call["user_id"] == 1
        assert call["channel_name"] == "#osu"

    async def test_session_not_found_does_nothing(
        self,
        handlers: ChatHandlers,
        leave_channel: StubLeaveChannelUseCase,
        session_store: StubSessionStore,
    ) -> None:
        """Session未発見のleave requestがuse caseを呼ばないことを検証する.

        Args:
            handlers (ChatHandlers): leave requestを処理するhandler集合.
            leave_channel (StubLeaveChannelUseCase): command記録を観測するstub.
            session_store (StubSessionStore): Noneを返すよう設定するstore stub.

        Returns:
            None: leave command記録が空であることを確認して完了する.
        """
        session_store.session = None

        payload = _build_banchostring_payload("#osu")

        await handlers.handle_leave_channel(payload, user_id=999)

        assert len(leave_channel.calls) == 0
