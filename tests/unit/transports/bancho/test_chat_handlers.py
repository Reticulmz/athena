"""Tests for ChatHandlers — C2S packet handlers 4種.

Validates:
- handle_send_message: Message struct パース → SendChannelMessageUseCase
- handle_send_private_message: Message struct パース → SendPrivateMessageUseCase
- handle_join_channel: BanchoString パース → JoinChannelUseCase
- handle_leave_channel: BanchoString パース → LeaveChannelUseCase
"""

from __future__ import annotations

import pytest
from caterpillar.model import pack

from osu_server.domain.chat import (
    ChannelMessageResult,
    ChatCommandResponse,
    PrivateMessageResult,
)
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.system_user import BANCHO_BOT_IDENTITY
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
from osu_server.transports.bancho.handlers.chat import ChatHandlers
from osu_server.transports.bancho.protocol.s2c.chat import send_message
from osu_server.transports.bancho.protocol.types import BanchoString, Message

# ── Stubs ────────────────────────────────────────────────────────────────


class StubSendChannelMessageUseCase:
    """SendChannelMessageUseCase spy."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.channel_result: ChannelMessageResult | None = ChannelMessageResult(
            delivered_to={2, 3}, content="hello", command_responses=()
        )

    async def execute(
        self,
        command: SendChannelMessageCommand,
    ) -> SendChannelMessageResult:
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
    """SendPrivateMessageUseCase spy."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.private_result: PrivateMessageResult | None = PrivateMessageResult(
            target_id=2, is_online=True, content="secret", command_responses=()
        )

    async def execute(
        self,
        command: SendPrivateMessageCommand,
    ) -> SendPrivateMessageResult:
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
    """JoinChannelUseCase spy."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute(
        self,
        command: JoinChannelCommand,
    ) -> JoinChannelResult:
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
    """LeaveChannelUseCase spy."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute(
        self,
        command: LeaveChannelCommand,
    ) -> None:
        self.calls.append(
            {
                "method": "leave",
                "user_id": command.user_id,
                "channel_name": command.channel_name,
            }
        )


class StubSessionStore:
    """SessionStore スタブ。"""

    session: SessionData | None

    def __init__(self, session: SessionData | None = None) -> None:
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
        return self.session


# ── Helpers ──────────────────────────────────────────────────────────────


def _build_message_payload(
    sender: str = "test_user",
    content: str = "hello",
    target: str = "#osu",
    sender_id: int = 1,
) -> bytes:
    msg = Message(sender=sender, content=content, target=target, sender_id=sender_id)
    return pack(msg)


def _build_banchostring_payload(value: str) -> bytes:
    return pack(value, BanchoString)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def send_channel_message() -> StubSendChannelMessageUseCase:
    return StubSendChannelMessageUseCase()


@pytest.fixture
def send_private_message() -> StubSendPrivateMessageUseCase:
    return StubSendPrivateMessageUseCase()


@pytest.fixture
def join_channel() -> StubJoinChannelUseCase:
    return StubJoinChannelUseCase()


@pytest.fixture
def leave_channel() -> StubLeaveChannelUseCase:
    return StubLeaveChannelUseCase()


@pytest.fixture
def session_store() -> StubSessionStore:
    return StubSessionStore()


@pytest.fixture
def packet_queue() -> InMemoryPacketQueue:
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
    return ChatHandlers(
        send_channel_message=send_channel_message,  # pyright: ignore[reportArgumentType]
        send_private_message=send_private_message,  # pyright: ignore[reportArgumentType]
        join_channel=join_channel,  # pyright: ignore[reportArgumentType]
        leave_channel=leave_channel,  # pyright: ignore[reportArgumentType]
        session_store=session_store,  # pyright: ignore[reportArgumentType]
        packet_queue=packet_queue,
    )


# ── handle_send_message ──────────────────────────────────────────────────


class TestSendMessage:
    async def test_parses_message_and_calls_send_channel_message(
        self,
        handlers: ChatHandlers,
        send_channel_message: StubSendChannelMessageUseCase,
        session_store: StubSessionStore,  # pyright: ignore[reportUnusedParameter]  # noqa: ARG002
    ) -> None:
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
        """PM guidance from a channel command is visible only to the sender."""
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
    async def test_parses_message_and_calls_send_private_message(
        self,
        handlers: ChatHandlers,
        send_private_message: StubSendPrivateMessageUseCase,
        session_store: StubSessionStore,  # pyright: ignore[reportUnusedParameter]  # noqa: ARG002
    ) -> None:
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
        session_store.session = None

        payload = _build_message_payload()

        await handlers.handle_send_private_message(payload, user_id=999)

        assert len(send_private_message.calls) == 0


# ── handle_join_channel ──────────────────────────────────────────────────


class TestJoinChannel:
    async def test_parses_channel_name_and_calls_join(
        self,
        handlers: ChatHandlers,
        join_channel: StubJoinChannelUseCase,
        session_store: StubSessionStore,
    ) -> None:
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
        session_store.session = None

        payload = _build_banchostring_payload("#osu")

        await handlers.handle_join_channel(payload, user_id=999)

        assert len(join_channel.calls) == 0


# ── authorization refresh observation ──────────────────────────────────────


class TestAuthorizationRefreshObservation:
    """handler は login-time のキャッシュ値ではなく action-time の session 認可を読む。"""

    async def test_updated_session_authorization_reflected_in_next_action(
        self,
        send_channel_message: StubSendChannelMessageUseCase,
        send_private_message: StubSendPrivateMessageUseCase,
        join_channel: StubJoinChannelUseCase,
        leave_channel: StubLeaveChannelUseCase,
        packet_queue: InMemoryPacketQueue,
    ) -> None:
        """session 認可が更新された後、次の C2S action で新しい値が観測される。"""
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
    async def test_parses_channel_name_and_calls_leave(
        self,
        handlers: ChatHandlers,
        leave_channel: StubLeaveChannelUseCase,
        session_store: StubSessionStore,  # pyright: ignore[reportUnusedParameter]  # noqa: ARG002
    ) -> None:
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
        session_store.session = None

        payload = _build_banchostring_payload("#osu")

        await handlers.handle_leave_channel(payload, user_id=999)

        assert len(leave_channel.calls) == 0
