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
from typing import TYPE_CHECKING, cast

from starlette.testclient import TestClient

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from tests.factories.domain import make_channel, make_channel_role_override
from tests.support.app import create_in_memory_app as create_app
from tests.support.persistence import seed_channel, seed_channel_override, seed_role_sync

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette

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
_BANCHO_URL = "http://c.athena.localhost/"

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
    old_environment = os.environ.get("ENVIRONMENT")
    old_domain = os.environ.get("DOMAIN")
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DOMAIN"] = "athena.localhost"
    _ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
    _ = os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")
    try:
        yield
    finally:
        if old_environment is None:
            _ = os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = old_environment
        if old_domain is None:
            _ = os.environ.pop("DOMAIN", None)
        else:
            os.environ["DOMAIN"] = old_domain


def _seed_default_role(app: Starlette) -> None:
    """Seed the Default role into command-side in-memory persistence.

    Must be called after TestClient enters (lifespan has run).
    """
    seed_role_sync(app, _DEFAULT_ROLE)


def _seed_default_channels(app: Starlette) -> None:
    """Seed login-visible channels into command-side in-memory persistence."""

    async def _seed() -> None:
        channel = await seed_channel(app, make_channel(id=0))
        await seed_channel_override(
            app,
            make_channel_role_override(
                channel_id=channel.id,
                role_id=_DEFAULT_ROLE.id,
            ),
        )

    asyncio.run(_seed())


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


# ── Test: Bancho routing ────────────────────────────────────────────────


class TestBanchoRouting:
    """Bancho POST traffic is routed by stable client hostnames."""

    def test_numbered_and_ce_hosts_reach_bancho_endpoint(self) -> None:
        """cN.$DOMAIN and ce.$DOMAIN hosts reach POST /."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                for url in (
                    "http://c4.athena.localhost/",
                    "http://c6.athena.localhost/",
                    "http://ce.athena.localhost/",
                ):
                    response = client.post(url)
                    assert response.status_code == HTTPStatus.OK

    def test_post_root_requires_bancho_host(self) -> None:
        """POST / without a bancho host is not a path fallback."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/")
                assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


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

                response = client.post(_BANCHO_URL, content=_login_body())

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

                response = client.post(_BANCHO_URL, content=_login_body())

                assert response.status_code == HTTPStatus.OK
                assert len(response.content) > _PACKET_HEADER_SIZE

    def test_register_then_login_accepts_uppercase_password_md5(self) -> None:
        """Stable login の password MD5 hex は大小文字差を認証差にしない."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post(
                    _BANCHO_URL,
                    content=_login_body(password_md5=_TEST_PASSWORD_MD5.upper()),
                )

                assert response.status_code == HTTPStatus.OK
                assert "cho-token" in response.headers


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

                response = client.post(_BANCHO_URL, content=_login_body())
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

                response = client.post(_BANCHO_URL, content=_login_body())
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

                response = client.post(_BANCHO_URL, content=_login_body())
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

                response = client.post(_BANCHO_URL, content=_login_body())
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

                login_resp = client.post(_BANCHO_URL, content=_login_body())
                token = login_resp.headers["cho-token"]

                poll_resp = client.post(_BANCHO_URL, headers={"osu-token": token})

                assert poll_resp.status_code == HTTPStatus.OK
                assert poll_resp.content == b""


class TestPresenceBroadcast:
    """Login live presence is delivered through the polling queue."""

    def test_second_login_enqueues_user_presence_for_existing_online_user(self) -> None:
        """When User B logs in, User A receives User B's USER_PRESENCE on next poll."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)
                second_register = client.post(
                    "/web/users",
                    data=_registration_form(
                        username="SecondUser",
                        email="second@example.com",
                    ),
                )
                assert second_register.status_code == HTTPStatus.OK

                login_a = client.post(_BANCHO_URL, content=_login_body())
                assert login_a.status_code == HTTPStatus.OK
                token_a = login_a.headers["cho-token"]

                first_poll = client.post(_BANCHO_URL, headers={"osu-token": token_a})
                assert first_poll.status_code == HTTPStatus.OK
                assert first_poll.content == b""

                login_b = client.post(
                    _BANCHO_URL,
                    content=_login_body(username="SecondUser"),
                )
                assert login_b.status_code == HTTPStatus.OK
                login_b_reply = _find_packet(
                    _parse_packets(login_b.content),
                    _LOGIN_REPLY_ID,
                )
                assert login_b_reply is not None
                user_b_id = cast("int", struct.unpack_from("<i", login_b_reply, 0)[0])

                second_poll = client.post(_BANCHO_URL, headers={"osu-token": token_a})
                assert second_poll.status_code == HTTPStatus.OK
                presence_packets = [
                    content
                    for packet_id, content in _parse_packets(second_poll.content)
                    if packet_id == ServerPacketID.USER_PRESENCE
                ]

                assert any(
                    cast("int", struct.unpack_from("<i", packet, 0)[0]) == user_b_id
                    for packet in presence_packets
                )


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

                resp1 = client.post(_BANCHO_URL, content=_login_body())
                token1 = resp1.headers["cho-token"]

                resp2 = client.post(_BANCHO_URL, content=_login_body())
                token2 = resp2.headers["cho-token"]

                assert token1 != token2

    def test_old_token_polling_fails_after_relogin(self) -> None:
        """After re-login, polling with the old token returns login_reply(-1)."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                resp1 = client.post(_BANCHO_URL, content=_login_body())
                old_token = resp1.headers["cho-token"]

                # Re-login
                _ = client.post(_BANCHO_URL, content=_login_body())

                # Poll with old token — should get authentication failure
                poll_resp = client.post(_BANCHO_URL, headers={"osu-token": old_token})
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

                _ = client.post(_BANCHO_URL, content=_login_body())

                resp2 = client.post(_BANCHO_URL, content=_login_body())
                new_token = resp2.headers["cho-token"]

                poll_resp = client.post(_BANCHO_URL, headers={"osu-token": new_token})

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
                    _BANCHO_URL,
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
                    _BANCHO_URL,
                    content=_login_body(password_md5=wrong_md5),
                )

                assert response.status_code == HTTPStatus.OK
                packets = _parse_packets(response.content)

                assert len(packets) > 0
                first_id, first_content = packets[0]
                assert first_id == _LOGIN_REPLY_ID
                user_id: int = struct.unpack("<i", first_content)[0]  # pyright: ignore[reportAny]  # struct.unpack returns tuple[Any, ...]
                assert user_id == _AUTH_FAILED_USER_ID
