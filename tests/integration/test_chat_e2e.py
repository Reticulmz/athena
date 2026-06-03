"""E2E chat + C2S regression tests (Task 5.3).

Tests the full login -> poll -> C2S dispatch -> S2C drain flow through
the refactored BanchoEndpoint + DI container, preserving all existing
packet behavior assertions for channel lifecycle, private messages,
and login channel list.

Uses the DI-registered ChatHandlers — no manual handler construction.
"""

from __future__ import annotations

import hashlib
import os
import struct
from http import HTTPStatus
from typing import TYPE_CHECKING

from caterpillar.model import pack
from starlette.testclient import TestClient

from osu_server.composition.application import create_app
from osu_server.domain.auth import RegistrationForm
from osu_server.domain.role import Privileges, Role
from osu_server.domain.system_user import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.repositories.interfaces.channel_repository import ChannelRepository
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.services.auth_service import AuthService
from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.protocol.s2c.chat import channel_join_success, send_message
from osu_server.transports.bancho.protocol.s2c.login import (
    channel_available,
    channel_available_autojoin,
    channel_info_complete,
    user_presence,
    user_presence_bundle,
)
from osu_server.transports.bancho.protocol.types import BanchoString, Message
from tests.factories.domain import make_channel, make_channel_role_override

if TYPE_CHECKING:
    from starlette.applications import Starlette

    from osu_server.infrastructure.di.container import Container

_PASSWORD = "SecurePass1234"
_PASSWORD_MD5 = hashlib.md5(_PASSWORD.encode()).hexdigest()
_CLIENT_INFO = "20231111|9|1|hash1:hash2:hash3|0"

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

# Module-level env defaults for test DI container
_ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
_ = os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")


# -- App / DI helpers --------------------------------------------------------


def _make_test_app() -> Starlette:
    """Create the Starlette app with full DI container and BanchoEndpoint."""
    os.environ["ENVIRONMENT"] = "test"
    return create_app()


def _seed_default_role(container: Container) -> None:
    """Seed the Default role into InMemoryRoleRepository after lifespan."""
    registration = container._registrations[RoleRepository]  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    repo = registration.instance
    assert isinstance(repo, InMemoryRoleRepository)
    repo._roles_by_id[_DEFAULT_ROLE.id] = _DEFAULT_ROLE  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    repo._roles_by_name[_DEFAULT_ROLE.name] = _DEFAULT_ROLE.id  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


async def _seed_channels(container: Container) -> None:
    """Seed channels and role overrides into InMemoryChannelRepository."""
    repo = await container.resolve(ChannelRepository)
    assert isinstance(repo, InMemoryChannelRepository)

    osu_channel = await repo.create(
        make_channel(name="#osu", topic="General discussion", auto_join=True),
    )
    announce_channel = await repo.create(
        make_channel(name="#announce", topic="Announcements", auto_join=False),
    )
    repo.seed_override(
        make_channel_role_override(channel_id=osu_channel.id, role_id=_DEFAULT_ROLE.id),
    )
    repo.seed_override(
        make_channel_role_override(
            channel_id=announce_channel.id,
            role_id=_DEFAULT_ROLE.id,
            can_read=True,
            can_write=False,
        ),
    )


async def _resolve_services(
    app: Starlette,
) -> tuple[AuthService, SessionStore, ChannelStateStore]:
    """Resolve test-facing services from the container after lifespan."""
    container: Container = app.state.container  # pyright: ignore[reportAny]
    _seed_default_role(container)
    await _seed_channels(container)
    return (
        await container.resolve(AuthService),
        await container.resolve(SessionStore),
        await container.resolve(ChannelStateStore),
    )


# -- Protocol helpers --------------------------------------------------------


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
        RegistrationForm(username=username, email=email, password=_PASSWORD),
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


async def _user_id_for_token(session_store: SessionStore, token: str) -> int:
    session = await session_store.get(token)
    assert session is not None
    return session.user_id


# ═══════════════════════════════════════════════════════════════════════════
# Channel Lifecycle
# ═══════════════════════════════════════════════════════════════════════════


class TestChannelLifecycleE2E:
    """JOIN_CHANNEL then SEND_MESSAGE reaches target via S2C drain (Req 5.1, 6.2)."""

    async def test_http_join_then_channel_message_reaches_target_poll_response(
        self,
    ) -> None:
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, session_store, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")
            await _register_user(auth_service, "Target", "target@example.com")

            sender_token = _login(client, "Sender")
            target_token = _login(client, "Target")
            sender_id = await _user_id_for_token(session_store, sender_token)

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


# ═══════════════════════════════════════════════════════════════════════════
# Private Messages
# ═══════════════════════════════════════════════════════════════════════════


class TestPrivateMessageE2E:
    """SEND_PRIVATE_MESSAGE reaches target via S2C drain (Req 5.1, 6.2)."""

    async def test_http_private_message_reaches_target_poll_response(self) -> None:
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, session_store, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")
            await _register_user(auth_service, "Target", "target@example.com")

            sender_token = _login(client, "Sender")
            target_token = _login(client, "Target")
            sender_id = await _user_id_for_token(session_store, sender_token)

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


# ═══════════════════════════════════════════════════════════════════════════
# Login Channel List
# ═══════════════════════════════════════════════════════════════════════════


class TestLoginChannelListE2E:
    """Login response contains DB-backed channel list (Req 1.5, 2.1, 2.2, 2.4)."""

    async def test_login_response_contains_db_backed_channel_list(self) -> None:
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, _, channel_state = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")
            await channel_state.add_member("#osu", 101)
            await channel_state.add_member("#announce", 202)

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


# ═══════════════════════════════════════════════════════════════════════════
# BanchoBot Identity E2E (Req 1.1, 1.2, 2.1, 2.2, 2.3, 3.1, 3.2)
# ═══════════════════════════════════════════════════════════════════════════


class TestBanchoBotIdentityE2E:
    """Login-to-command BanchoBot identity consistency (Req 1.1-2.3, 3.1-3.2)."""

    async def test_login_response_contains_banchobot_presence(self) -> None:
        """Login response has BanchoBot USER_PRESENCE with correct identity."""
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, _, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")

            response = client.post("/", content=_login_body("Sender"))

        assert response.status_code == HTTPStatus.OK
        banchobot_presence = user_presence(
            user_id=BANCHO_BOT_IDENTITY.user_id,
            username=BANCHO_BOT_IDENTITY.username,
            timezone=24,
            country_id=0,
            permissions=0,
            mode=0,
            longitude=0.0,
            latitude=0.0,
            rank=0,
        )
        assert banchobot_presence in response.content

    async def test_login_response_contains_banchobot_bundle(self) -> None:
        """USER_PRESENCE_BUNDLE includes BanchoBot ID and the connecting user,
        with no duplicate entries."""
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, session_store, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")

            response = client.post("/", content=_login_body("Sender"))
            user_id = await _user_id_for_token(session_store, response.headers["cho-token"])

        assert response.status_code == HTTPStatus.OK
        roster_ids = list(dict.fromkeys([BANCHO_BOT_IDENTITY.user_id, user_id]))
        expected_bundle = user_presence_bundle(roster_ids)
        assert expected_bundle in response.content

    async def test_banchobot_presence_before_bundle(self) -> None:
        """BanchoBot USER_PRESENCE appears before USER_PRESENCE_BUNDLE
        so the client knows BanchoBot identity before processing roster."""
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, _, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")

            response = client.post("/", content=_login_body("Sender"))

        assert response.status_code == HTTPStatus.OK
        banchobot_presence = user_presence(
            user_id=BANCHO_BOT_IDENTITY.user_id,
            username=BANCHO_BOT_IDENTITY.username,
            timezone=24,
            country_id=0,
            permissions=0,
            mode=0,
            longitude=0.0,
            latitude=0.0,
            rank=0,
        )
        bundle_marker = user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, 2])
        presence_pos = response.content.index(banchobot_presence)
        bundle_pos = response.content.index(bundle_marker)
        assert presence_pos < bundle_pos, (
            "BanchoBot USER_PRESENCE must precede USER_PRESENCE_BUNDLE"
        )

    async def test_human_user_in_roster_with_banchobot(self) -> None:
        """Human user is present in roster alongside BanchoBot (Req 3.1, 3.2).
        The USER_PRESENCE_BUNDLE contains both IDs without duplicates."""
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, session_store, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")

            response = client.post("/", content=_login_body("Sender"))
            user_id = await _user_id_for_token(session_store, response.headers["cho-token"])

        assert response.status_code == HTTPStatus.OK
        roster_ids = list(dict.fromkeys([BANCHO_BOT_IDENTITY.user_id, user_id]))
        expected_bundle = user_presence_bundle(roster_ids)
        assert expected_bundle in response.content
        # BanchoBot is always present
        assert BANCHO_BOT_IDENTITY.user_id in roster_ids
        # Human user is never hidden or replaced by BanchoBot
        assert user_id in roster_ids
        if user_id != BANCHO_BOT_IDENTITY.user_id:
            assert len(roster_ids) == 2

    async def test_command_response_uses_banchobot_identity(self) -> None:
        """After login, !help command response uses the same BanchoBot identity
        exposed in the login roster (Req 2.1, 2.2, 2.3, 4.1, 4.3)."""
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, _, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")

            token = _login(client, "Sender")
            assert _poll(client, token) == b""

            join_resp = _poll(
                client,
                token,
                _c2s_packet(
                    ClientPacketID.JOIN_CHANNEL,
                    _channel_payload("#osu"),
                ),
            )
            assert join_resp == channel_join_success(channel_name="#osu")

            poll_resp = _poll(
                client,
                token,
                _c2s_packet(
                    ClientPacketID.SEND_MESSAGE,
                    _message_payload(
                        sender="Sender",
                        content="!help",
                        target="#osu",
                        sender_id=0,
                    ),
                ),
            )
            # The poll response contains BanchoBot's response
            banchobot_message = send_message(
                sender=BANCHO_BOT_IDENTITY.username,
                content="Available commands: !roll, !help",
                target="#osu",
                sender_id=BANCHO_BOT_IDENTITY.user_id,
            )
            assert banchobot_message in poll_resp
