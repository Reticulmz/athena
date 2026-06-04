"""Tests for ChatHandlers — C2S packet handlers 4種.

Validates:
- handle_send_message: Message struct パース → chat_service.send_channel_message()
- handle_send_private_message: Message struct パース → chat_service.send_private_message()
- handle_join_channel: BanchoString パース → channel_service.join()
- handle_leave_channel: BanchoString パース → channel_service.leave()
"""

from __future__ import annotations

import pytest
from caterpillar.model import pack

from osu_server.domain.chat import (
    ChannelMessageResult,
    PrivateMessageResult,
    SendChannelMessageInput,
    SendPrivateMessageInput,
)
from osu_server.domain.session import SessionData
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.transports.bancho.handlers.chat import ChatHandlers
from osu_server.transports.bancho.protocol.types import BanchoString, Message

# ── Stubs ────────────────────────────────────────────────────────────────


class StubChatService:
    """ChatService スパイ。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.channel_result: ChannelMessageResult | None = ChannelMessageResult(
            delivered_to={2, 3}, content="hello", command_responses=()
        )
        self.private_result: PrivateMessageResult | None = PrivateMessageResult(
            target_id=2, is_online=True, content="secret", command_responses=()
        )

    async def send_channel_message(
        self,
        message: SendChannelMessageInput,
    ) -> ChannelMessageResult | None:
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
        return self.channel_result

    async def send_private_message(
        self,
        message: SendPrivateMessageInput,
    ) -> PrivateMessageResult | None:
        self.calls.append(
            {
                "method": "send_private_message",
                "sender_id": message.sender.user_id,
                "sender_name": message.sender.username,
                "target_name": message.destination.username,
                "content": message.content,
            }
        )
        return self.private_result


class StubChannelService:
    """ChannelService スパイ。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def join(
        self,
        *,
        user_id: int,
        user_privileges: int,
        user_role_ids: list[int],
        channel_name: str,
    ) -> bool:
        self.calls.append(
            {
                "method": "join",
                "user_id": user_id,
                "user_privileges": user_privileges,
                "user_role_ids": user_role_ids,
                "channel_name": channel_name,
            }
        )
        return True

    async def leave(
        self,
        *,
        user_id: int,
        channel_name: str,
    ) -> None:
        self.calls.append(
            {
                "method": "leave",
                "user_id": user_id,
                "channel_name": channel_name,
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
def chat_service() -> StubChatService:
    return StubChatService()


@pytest.fixture
def channel_service() -> StubChannelService:
    return StubChannelService()


@pytest.fixture
def session_store() -> StubSessionStore:
    return StubSessionStore()


@pytest.fixture
def packet_queue() -> InMemoryPacketQueue:
    return InMemoryPacketQueue()


@pytest.fixture
def handlers(
    chat_service: StubChatService,
    channel_service: StubChannelService,
    session_store: StubSessionStore,
    packet_queue: InMemoryPacketQueue,
) -> ChatHandlers:
    return ChatHandlers(
        chat_service=chat_service,  # pyright: ignore[reportArgumentType]
        channel_service=channel_service,  # pyright: ignore[reportArgumentType]
        session_store=session_store,  # pyright: ignore[reportArgumentType]
        packet_queue=packet_queue,
    )


# ── handle_send_message ──────────────────────────────────────────────────


class TestSendMessage:
    async def test_parses_message_and_calls_send_channel_message(
        self,
        handlers: ChatHandlers,
        chat_service: StubChatService,
        session_store: StubSessionStore,  # pyright: ignore[reportUnusedParameter]  # noqa: ARG002
    ) -> None:
        payload = _build_message_payload(
            sender="test_user", content="hello", target="#osu", sender_id=1
        )

        await handlers.handle_send_message(payload, user_id=1)

        assert len(chat_service.calls) == 1
        call = chat_service.calls[0]
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
        chat_service: StubChatService,
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

        assert chat_service.calls[0]["user_privileges"] == 8
        assert chat_service.calls[0]["user_role_ids"] == (1, 2)

    async def test_session_not_found_does_nothing(
        self,
        chat_service: StubChatService,
        channel_service: StubChannelService,
        session_store: StubSessionStore,
        packet_queue: InMemoryPacketQueue,
    ) -> None:
        session_store.session = None
        handlers = ChatHandlers(
            chat_service=chat_service,  # pyright: ignore[reportArgumentType]
            channel_service=channel_service,  # pyright: ignore[reportArgumentType]
            session_store=session_store,  # pyright: ignore[reportArgumentType]
            packet_queue=packet_queue,
        )

        payload = _build_message_payload()

        await handlers.handle_send_message(payload, user_id=999)

        assert len(chat_service.calls) == 0


# ── handle_send_private_message ──────────────────────────────────────────


class TestSendPrivateMessage:
    async def test_parses_message_and_calls_send_private_message(
        self,
        handlers: ChatHandlers,
        chat_service: StubChatService,
        session_store: StubSessionStore,  # pyright: ignore[reportUnusedParameter]  # noqa: ARG002
    ) -> None:
        payload = _build_message_payload(
            sender="test_user", content="secret", target="target", sender_id=1
        )

        await handlers.handle_send_private_message(payload, user_id=1)

        assert len(chat_service.calls) == 1
        call = chat_service.calls[0]
        assert call["method"] == "send_private_message"
        assert call["sender_id"] == 1
        assert call["sender_name"] == "test_user"
        assert call["target_name"] == "target"
        assert call["content"] == "secret"

    async def test_session_not_found_does_nothing(
        self,
        handlers: ChatHandlers,
        chat_service: StubChatService,
        session_store: StubSessionStore,
    ) -> None:
        session_store.session = None

        payload = _build_message_payload()

        await handlers.handle_send_private_message(payload, user_id=999)

        assert len(chat_service.calls) == 0


# ── handle_join_channel ──────────────────────────────────────────────────


class TestJoinChannel:
    async def test_parses_channel_name_and_calls_join(
        self,
        handlers: ChatHandlers,
        channel_service: StubChannelService,
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

        assert len(channel_service.calls) == 1
        call = channel_service.calls[0]
        assert call["method"] == "join"
        assert call["user_id"] == 1
        assert call["channel_name"] == "#osu"
        assert call["user_privileges"] == 8
        assert call["user_role_ids"] == [1, 2]

    async def test_session_not_found_does_nothing(
        self,
        handlers: ChatHandlers,
        channel_service: StubChannelService,
        session_store: StubSessionStore,
    ) -> None:
        session_store.session = None

        payload = _build_banchostring_payload("#osu")

        await handlers.handle_join_channel(payload, user_id=999)

        assert len(channel_service.calls) == 0


# ── authorization refresh observation ──────────────────────────────────────


class TestAuthorizationRefreshObservation:
    """handler は login-time のキャッシュ値ではなく action-time の session 認可を読む。"""

    async def test_updated_session_authorization_reflected_in_next_action(
        self,
        chat_service: StubChatService,
        channel_service: StubChannelService,
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
            chat_service=chat_service,  # pyright: ignore[reportArgumentType]
            channel_service=channel_service,  # pyright: ignore[reportArgumentType]
            session_store=store,  # pyright: ignore[reportArgumentType]
            packet_queue=packet_queue,
        )

        # First action: initial authorization
        await handlers.handle_send_message(_build_message_payload(), user_id=1)
        assert chat_service.calls[0]["user_privileges"] == 4
        assert chat_service.calls[0]["user_role_ids"] == (1,)

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
        assert chat_service.calls[1]["user_privileges"] == 260
        assert chat_service.calls[1]["user_role_ids"] == (1, 4)


# ── handle_leave_channel ─────────────────────────────────────────────────


class TestLeaveChannel:
    async def test_parses_channel_name_and_calls_leave(
        self,
        handlers: ChatHandlers,
        channel_service: StubChannelService,
        session_store: StubSessionStore,  # pyright: ignore[reportUnusedParameter]  # noqa: ARG002
    ) -> None:
        payload = _build_banchostring_payload("#osu")

        await handlers.handle_leave_channel(payload, user_id=1)

        assert len(channel_service.calls) == 1
        call = channel_service.calls[0]
        assert call["method"] == "leave"
        assert call["user_id"] == 1
        assert call["channel_name"] == "#osu"

    async def test_session_not_found_does_nothing(
        self,
        handlers: ChatHandlers,
        channel_service: StubChannelService,
        session_store: StubSessionStore,
    ) -> None:
        session_store.session = None

        payload = _build_banchostring_payload("#osu")

        await handlers.handle_leave_channel(payload, user_id=999)

        assert len(channel_service.calls) == 0
