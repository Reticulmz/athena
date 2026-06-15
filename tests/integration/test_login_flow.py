"""E2E integration tests for the osu! stable bancho login and polling flow.

Tests the full register -> login -> polling cycle through all layers
with InMemory repositories (ENVIRONMENT=test).

Covers:
- Registration + login flow: POST /web/users -> POST / -> cho-token + packet stream
- Login success: packet stream contains login_reply(positive user_id),
  protocol_version, login_permissions
- Polling stub: login -> cho-token POST / -> 200 empty body
- Re-login: new cho-token + old token polling failure
- Authentication failure: unregistered user -> login_reply(-1)
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import struct
from contextlib import contextmanager
from http import HTTPStatus
from typing import TYPE_CHECKING

from starlette.testclient import TestClient

from osu_server.app import create_app
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.repositories.interfaces.channel_repository import ChannelRepository
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from tests.factories.domain import make_channel, make_channel_role_override

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette

    from osu_server.infrastructure.di.container import Container

# ── Constants ────────────────────────────────────────────────────────────

_TEST_USERNAME = "TestPlayer"
_TEST_EMAIL = "test@example.com"
_TEST_PASSWORD = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD.encode()).hexdigest()
_TEST_CLIENT_INFO = "b20240101.1|9|1|abc:def:ghi:jkl:mno|0"

_LOGIN_REPLY_ID = int(ServerPacketID.LOGIN_REPLY)
_PROTOCOL_VERSION_ID = int(ServerPacketID.PROTOCOL_VERSION)
_LOGIN_PERMISSIONS_ID = int(ServerPacketID.LOGIN_PERMISSIONS)

_PACKET_HEADER_SIZE = 7  # 2 (id) + 1 (compression) + 4 (content_length)

_AUTH_FAILED_USER_ID = -1

_DEFAULT_ROLE = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED,
    position=0,
)

_EXPECTED_MIN_PACKETS = 10


# ── Helpers ──────────────────────────────────────────────────────────────


@contextmanager
def _test_env() -> Generator[None]:
    """Temporarily set ENVIRONMENT=test for the duration of the block."""
    old = os.environ.get("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "test"
    _ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
    _ = os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")
    try:
        yield
    finally:
        if old is None:
            _ = os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = old


def _seed_default_role(app: Starlette) -> None:
    """Seed the Default role into the InMemoryRoleRepository.

    Must be called after TestClient enters (lifespan has run).
    """
    container: Container = app.state.container  # pyright: ignore[reportAny]  # Starlette State returns Any
    registration = container._registrations[RoleRepository]  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]  # test-only DI introspection
    repo = registration.instance
    assert isinstance(repo, InMemoryRoleRepository)
    repo._roles_by_id[_DEFAULT_ROLE.id] = _DEFAULT_ROLE  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]  # test-only seed
    repo._roles_by_name[_DEFAULT_ROLE.name] = _DEFAULT_ROLE.id  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]  # test-only seed


def _seed_default_channels(app: Starlette) -> None:
    """Seed login-visible channels into the InMemoryChannelRepository."""
    container: Container = app.state.container  # pyright: ignore[reportAny]  # Starlette State returns Any
    registration = container._registrations[ChannelRepository]  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]  # test-only DI introspection
    repo = registration.instance
    assert isinstance(repo, InMemoryChannelRepository)

    channel = asyncio.run(repo.create(make_channel(id=0)))
    repo.seed_override(
        make_channel_role_override(
            channel_id=channel.id,
            role_id=_DEFAULT_ROLE.id,
        )
    )


def _seed_test_data(app: Starlette) -> None:
    """Seed default role and channels required by successful login tests."""
    _seed_default_role(app)
    _seed_default_channels(app)


def _registration_form(
    *,
    username: str = _TEST_USERNAME,
    email: str = _TEST_EMAIL,
    password: str = _TEST_PASSWORD,
) -> dict[str, str]:
    """Build a registration form data dict with check=0 (create account)."""
    return {
        "user[username]": username,
        "user[user_email]": email,
        "user[password]": password,
        "check": "0",
    }


def _login_body(
    *,
    username: str = _TEST_USERNAME,
    password_md5: str = _TEST_PASSWORD_MD5,
    client_info: str = _TEST_CLIENT_INFO,
) -> bytes:
    """Build a raw login request body in osu! stable format."""
    return f"{username}\n{password_md5}\n{client_info}\n".encode()


def _register_user(client: TestClient) -> None:
    """Register the default test user. Asserts success."""
    resp = client.post("/web/users", data=_registration_form())
    assert resp.status_code == HTTPStatus.OK, f"Registration failed: {resp.content!r}"


def _parse_packets(body: bytes) -> list[tuple[int, bytes]]:
    """Parse a concatenated S2C packet stream into (packet_id, content) pairs."""
    packets: list[tuple[int, bytes]] = []
    offset = 0
    while offset + _PACKET_HEADER_SIZE <= len(body):
        packet_id: int = struct.unpack_from("<H", body, offset)[0]  # pyright: ignore[reportAny]  # struct.unpack_from returns tuple[Any, ...]
        content_len: int = struct.unpack_from("<I", body, offset + 3)[0]  # pyright: ignore[reportAny]  # struct.unpack_from returns tuple[Any, ...]
        content_start = offset + _PACKET_HEADER_SIZE
        content_end: int = content_start + content_len
        if content_end > len(body):
            break
        content = body[content_start:content_end]
        packets.append((packet_id, content))
        offset = content_end
    return packets


def _find_packet(
    packets: list[tuple[int, bytes]],
    packet_id: int,
) -> bytes | None:
    """Find the first packet with the given ID and return its content."""
    for pid, content in packets:
        if pid == packet_id:
            return content
    return None


# ── Test: Full registration + login flow ─────────────────────────────────


class TestRegisterAndLoginFlow:
    """Register via POST /web/users then login via POST / and verify response."""

    def test_register_then_login_returns_cho_token(self) -> None:
        """POST /web/users (check=0) -> ok -> POST / (credentials) -> cho-token header."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post("/", content=_login_body())

                assert response.status_code == HTTPStatus.OK
                assert "cho-token" in response.headers
                assert len(response.headers["cho-token"]) > 0

    def test_register_then_login_returns_packet_stream(self) -> None:
        """Login response body is a non-empty S2C packet stream."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post("/", content=_login_body())

                assert response.status_code == HTTPStatus.OK
                assert len(response.content) > _PACKET_HEADER_SIZE


# ── Test: Login success packet verification ──────────────────────────────


class TestLoginSuccessPackets:
    """Verify the S2C packet stream content for a successful login."""

    def test_login_reply_contains_positive_user_id(self) -> None:
        """First packet is login_reply with a positive user_id."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post("/", content=_login_body())
                packets = _parse_packets(response.content)

                assert len(packets) > 0
                first_id, first_content = packets[0]
                assert first_id == _LOGIN_REPLY_ID
                user_id: int = struct.unpack("<i", first_content)[0]  # pyright: ignore[reportAny]  # struct.unpack returns tuple[Any, ...]
                assert user_id > 0

    def test_packet_stream_contains_protocol_version(self) -> None:
        """Packet stream includes a protocol_version packet."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post("/", content=_login_body())
                packets = _parse_packets(response.content)

                content = _find_packet(packets, _PROTOCOL_VERSION_ID)
                assert content is not None, "protocol_version packet not found in stream"
                version: int = struct.unpack("<i", content)[0]  # pyright: ignore[reportAny]  # struct.unpack returns tuple[Any, ...]
                assert version > 0

    def test_packet_stream_contains_login_permissions(self) -> None:
        """Packet stream includes a login_permissions packet."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post("/", content=_login_body())
                packets = _parse_packets(response.content)

                content = _find_packet(packets, _LOGIN_PERMISSIONS_ID)
                assert content is not None, "login_permissions packet not found in stream"

    def test_packet_stream_has_expected_packet_count(self) -> None:
        """Login response contains all 10 expected S2C packets."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post("/", content=_login_body())
                packets = _parse_packets(response.content)

                assert len(packets) >= _EXPECTED_MIN_PACKETS, (
                    f"Expected at least {_EXPECTED_MIN_PACKETS} packets, got {len(packets)}"
                )


# ── Test: Polling stub ───────────────────────────────────────────────────


class TestPollingStub:
    """Login -> cho-token -> POST / with osu-token header -> 200 empty body."""

    def test_polling_with_valid_token_returns_empty_body(self) -> None:
        """POST / with valid osu-token returns 200 with empty body."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                login_resp = client.post("/", content=_login_body())
                token = login_resp.headers["cho-token"]

                poll_resp = client.post("/", headers={"osu-token": token})

                assert poll_resp.status_code == HTTPStatus.OK
                assert poll_resp.content == b""


# ── Test: Re-login ───────────────────────────────────────────────────────


class TestReLogin:
    """Re-login replaces the session: new token issued, old token invalidated."""

    def test_relogin_returns_new_token(self) -> None:
        """Second login returns a different cho-token."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                resp1 = client.post("/", content=_login_body())
                token1 = resp1.headers["cho-token"]

                resp2 = client.post("/", content=_login_body())
                token2 = resp2.headers["cho-token"]

                assert token1 != token2

    def test_old_token_polling_fails_after_relogin(self) -> None:
        """After re-login, polling with the old token returns login_reply(-1)."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                resp1 = client.post("/", content=_login_body())
                old_token = resp1.headers["cho-token"]

                # Re-login
                _ = client.post("/", content=_login_body())

                # Poll with old token — should get authentication failure
                poll_resp = client.post("/", headers={"osu-token": old_token})
                packets = _parse_packets(poll_resp.content)

                assert len(packets) > 0
                first_id, first_content = packets[0]
                assert first_id == _LOGIN_REPLY_ID
                user_id: int = struct.unpack("<i", first_content)[0]  # pyright: ignore[reportAny]  # struct.unpack returns tuple[Any, ...]
                assert user_id == _AUTH_FAILED_USER_ID

    def test_new_token_polling_succeeds_after_relogin(self) -> None:
        """After re-login, polling with the new token succeeds."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                _ = client.post("/", content=_login_body())

                resp2 = client.post("/", content=_login_body())
                new_token = resp2.headers["cho-token"]

                poll_resp = client.post("/", headers={"osu-token": new_token})

                assert poll_resp.status_code == HTTPStatus.OK
                assert poll_resp.content == b""


# ── Test: Authentication failure ─────────────────────────────────────────


class TestAuthenticationFailure:
    """Login with invalid credentials returns login_reply with negative user_id."""

    def test_unregistered_user_returns_auth_failed(self) -> None:
        """Login with a username that was never registered returns login_reply(-1)."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/",
                    content=_login_body(username="NonExistentUser"),
                )

                assert response.status_code == HTTPStatus.OK
                packets = _parse_packets(response.content)

                assert len(packets) > 0
                first_id, first_content = packets[0]
                assert first_id == _LOGIN_REPLY_ID
                user_id: int = struct.unpack("<i", first_content)[0]  # pyright: ignore[reportAny]  # struct.unpack returns tuple[Any, ...]
                assert user_id == _AUTH_FAILED_USER_ID

    def test_wrong_password_returns_auth_failed(self) -> None:
        """Login with correct username but wrong password returns login_reply(-1)."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                wrong_md5 = hashlib.md5(b"wrongpassword").hexdigest()
                response = client.post(
                    "/",
                    content=_login_body(password_md5=wrong_md5),
                )

                assert response.status_code == HTTPStatus.OK
                packets = _parse_packets(response.content)

                assert len(packets) > 0
                first_id, first_content = packets[0]
                assert first_id == _LOGIN_REPLY_ID
                user_id: int = struct.unpack("<i", first_content)[0]  # pyright: ignore[reportAny]  # struct.unpack returns tuple[Any, ...]
                assert user_id == _AUTH_FAILED_USER_ID
