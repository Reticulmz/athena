from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

from caterpillar.model import pack
from pydantic import PostgresDsn, RedisDsn
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from osu_server.config import AppConfig
from osu_server.domain.auth import RegistrationForm
from osu_server.domain.role import Privileges, Role
from osu_server.infrastructure.messaging.memory import InMemoryEventBus
from osu_server.infrastructure.state.memory.channel_state_store import (
    InMemoryChannelStateStore,
)
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.chat_repository import InMemoryChatRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.auth_service import AuthService
from osu_server.services.channel_service import ChannelService
from osu_server.services.chat_service import ChatService
from osu_server.services.command_service import CommandService
from osu_server.services.password_service import PasswordService
from osu_server.services.permission_service import PermissionService
from osu_server.services.private_message_service import PrivateMessageService
from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.handlers.chat import ChatHandlers
from osu_server.transports.bancho.handlers.login import LoginHandler
from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.protocol.s2c.chat import channel_join_success, send_message
from osu_server.transports.bancho.protocol.s2c.login import (
    channel_available,
    channel_available_autojoin,
    channel_info_complete,
)
from osu_server.transports.bancho.protocol.types import BanchoString, Message
from tests.factories.domain import make_channel, make_channel_role_override

if TYPE_CHECKING:
    from collections.abc import Mapping

_PASSWORD = "SecurePass1234"
_PASSWORD_MD5 = hashlib.md5(_PASSWORD.encode()).hexdigest()
_CLIENT_INFO = "20231111|9|1|hash1:hash2:hash3|0"
_PACKET_QUEUE_TTL = 300

_DEFAULT_ROLE = Role(
    id=1,
    name="Default",
    permissions=(
        Privileges.NORMAL
        | Privileges.VERIFIED
        | Privileges.UNRESTRICTED
        | Privileges.BYPASS_CHANNEL_ACL
    ),
    position=0,
)


class _StubCountryResolver:
    def resolve(self, headers: Mapping[str, str]) -> str:
        _ = headers
        return "JP"


@dataclass(slots=True)
class ChatE2EApp:
    app: Starlette
    auth_service: AuthService
    channel_state: InMemoryChannelStateStore
    session_store: InMemorySessionStore


async def _make_chat_e2e_app() -> ChatE2EApp:
    user_repo = InMemoryUserRepository()
    role_repo = InMemoryRoleRepository(seed_roles=[_DEFAULT_ROLE])
    session_store = InMemorySessionStore()
    channel_repo = InMemoryChannelRepository()
    channel_state = InMemoryChannelStateStore()
    packet_queue = InMemoryPacketQueue()
    event_bus = InMemoryEventBus()
    dispatcher = PacketDispatcher()

    osu_channel = await channel_repo.create(
        make_channel(name="#osu", topic="General discussion", auto_join=True)
    )
    announce_channel = await channel_repo.create(
        make_channel(name="#announce", topic="Announcements", auto_join=False)
    )
    channel_repo.seed_override(
        make_channel_role_override(channel_id=osu_channel.id, role_id=_DEFAULT_ROLE.id)
    )
    channel_repo.seed_override(
        make_channel_role_override(
            channel_id=announce_channel.id,
            role_id=_DEFAULT_ROLE.id,
            can_read=True,
            can_write=False,
        )
    )

    permission_service = PermissionService(role_repo=role_repo)
    auth_service = AuthService(
        user_repo=user_repo,
        role_repo=role_repo,
        password_service=PasswordService(hibp_client=None, banned_passwords=[]),
        permission_service=permission_service,
        session_store=session_store,
    )
    channel_service = ChannelService(
        channel_repo=channel_repo,
        channel_state=channel_state,
    )
    chat_service = ChatService(
        channel_service=channel_service,
        private_message_service=PrivateMessageService(
            user_repo=user_repo,
            session_store=session_store,
        ),
        command_service=CommandService(),
        session_store=session_store,
        event_bus=event_bus,
        rate_limiter=InMemoryRateLimiter(time_func=lambda: 0.0),
        config=AppConfig(
            database_url=PostgresDsn("postgresql+asyncpg://test"),
            valkey_url=RedisDsn("redis://test"),
            message_max_length=450,
            rate_limit_messages=10,
            rate_limit_window=10,
        ),
        chat_repository=InMemoryChatRepository(),
    )
    chat_handlers = ChatHandlers(
        chat_service=chat_service,
        channel_service=channel_service,
        session_store=session_store,
        packet_queue=packet_queue,
    )
    chat_handlers.register_all(dispatcher)

    login_handler = LoginHandler(
        auth_service=auth_service,
        session_store=session_store,
        country_resolver=_StubCountryResolver(),
        channel_service=channel_service,
        packet_queue=packet_queue,
        packet_dispatcher=dispatcher,
        session_ttl=_PACKET_QUEUE_TTL,
    )
    app = Starlette(routes=[Route("/", login_handler.__call__, methods=["POST"])])
    return ChatE2EApp(
        app=app,
        auth_service=auth_service,
        channel_state=channel_state,
        session_store=session_store,
    )


def _login_body(username: str) -> bytes:
    return f"{username}\n{_PASSWORD_MD5}\n{_CLIENT_INFO}\n".encode()


def _c2s_packet(packet_id: ClientPacketID, payload: bytes) -> bytes:
    return struct.pack("<HBI", packet_id.value, 0, len(payload)) + payload


def _channel_payload(channel_name: str) -> bytes:
    return pack(channel_name, BanchoString)


def _message_payload(*, sender: str, content: str, target: str, sender_id: int) -> bytes:
    return pack(Message(sender=sender, content=content, target=target, sender_id=sender_id))


async def _register_user(auth_service: AuthService, username: str, email: str) -> None:
    result = await auth_service.register(
        RegistrationForm(username=username, email=email, password=_PASSWORD)
    )
    assert result.success is True


def _login(client: TestClient, username: str) -> str:
    response = client.post("/", content=_login_body(username))
    assert response.status_code == HTTPStatus.OK
    return response.headers["cho-token"]


def _poll(client: TestClient, token: str, content: bytes = b"") -> bytes:
    response = client.post("/", headers={"osu-token": token}, content=content)
    assert response.status_code == HTTPStatus.OK
    return response.content


async def _user_id_for_token(app: ChatE2EApp, token: str) -> int:
    session = await app.session_store.get(token)
    assert session is not None
    return session.user_id


class TestChannelLifecycleE2E:
    async def test_http_join_then_channel_message_reaches_target_poll_response(
        self,
    ) -> None:
        e2e = await _make_chat_e2e_app()
        await _register_user(e2e.auth_service, "Sender", "sender@example.com")
        await _register_user(e2e.auth_service, "Target", "target@example.com")

        with TestClient(e2e.app) as client:
            sender_token = _login(client, "Sender")
            target_token = _login(client, "Target")
            sender_id = await _user_id_for_token(e2e, sender_token)

            assert _poll(client, sender_token) == b""
            assert _poll(client, target_token) == b""

            target_join = _poll(
                client,
                target_token,
                _c2s_packet(ClientPacketID.JOIN_CHANNEL, _channel_payload("#osu")),
            )
            assert target_join == channel_join_success(channel_name="#osu")

            sender_join = _poll(
                client,
                sender_token,
                _c2s_packet(ClientPacketID.JOIN_CHANNEL, _channel_payload("#osu")),
            )
            assert sender_join == channel_join_success(channel_name="#osu")

            sender_response = _poll(
                client,
                sender_token,
                _c2s_packet(
                    ClientPacketID.SEND_MESSAGE,
                    _message_payload(
                        sender="Sender",
                        content="hello channel",
                        target="#osu",
                        sender_id=sender_id,
                    ),
                ),
            )
            assert sender_response == b""

            target_response = _poll(client, target_token)
            assert target_response == send_message(
                sender="Sender",
                content="hello channel",
                target="#osu",
                sender_id=sender_id,
            )


class TestPrivateMessageE2E:
    async def test_http_private_message_reaches_target_poll_response(self) -> None:
        e2e = await _make_chat_e2e_app()
        await _register_user(e2e.auth_service, "Sender", "sender@example.com")
        await _register_user(e2e.auth_service, "Target", "target@example.com")

        with TestClient(e2e.app) as client:
            sender_token = _login(client, "Sender")
            target_token = _login(client, "Target")
            sender_id = await _user_id_for_token(e2e, sender_token)

            assert _poll(client, sender_token) == b""
            assert _poll(client, target_token) == b""

            sender_response = _poll(
                client,
                sender_token,
                _c2s_packet(
                    ClientPacketID.SEND_PRIVATE_MESSAGE,
                    _message_payload(
                        sender="Sender",
                        content="hello pm",
                        target="Target",
                        sender_id=sender_id,
                    ),
                ),
            )
            assert sender_response == b""

            target_response = _poll(client, target_token)
            assert target_response == send_message(
                sender="Sender",
                content="hello pm",
                target="Target",
                sender_id=sender_id,
            )


class TestLoginChannelListE2E:
    async def test_login_response_contains_db_backed_channel_list(self) -> None:
        e2e = await _make_chat_e2e_app()
        await _register_user(e2e.auth_service, "Sender", "sender@example.com")
        await e2e.channel_state.add_member("#osu", 101)
        await e2e.channel_state.add_member("#announce", 202)

        with TestClient(e2e.app) as client:
            response = client.post("/", content=_login_body("Sender"))

        assert response.status_code == HTTPStatus.OK
        assert (
            channel_available(
                name="#osu",
                topic="General discussion",
                user_count=1,
            )
            in response.content
        )
        assert (
            channel_available(
                name="#announce",
                topic="Announcements",
                user_count=1,
            )
            in response.content
        )
        assert (
            channel_available_autojoin(
                name="#osu",
                topic="General discussion",
                user_count=1,
            )
            in response.content
        )
        assert channel_info_complete() in response.content
