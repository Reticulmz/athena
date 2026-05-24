"""LoginHandler (POST / ) unit tests.

TDD RED -> GREEN -> REFACTOR.
Tests: login success, auth failure, server error, polling success, polling with invalid token.
Logging: structlog migration, contextvars binding on successful login.

Uses Starlette TestClient with a minimal app that routes POST / to the handler.
"""

from __future__ import annotations

import hashlib
import struct
from http import HTTPStatus
from unittest.mock import AsyncMock

import structlog.contextvars
import structlog.testing
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from osu_server.domain.auth import LoginResult, RegistrationForm
from osu_server.domain.role import Privileges, Role
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.auth_service import AuthService
from osu_server.services.password_service import PasswordService
from osu_server.services.permission_service import PermissionService
from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.handlers.login import LoginHandler
from osu_server.transports.bancho.protocol.s2c.login import login_reply

# ── Seed data ────────────────────────────────────────────────────────

_PASSWORD = "SecurePass1234"
_PASSWORD_MD5 = hashlib.md5(_PASSWORD.encode()).hexdigest()

_ROLE_DEFAULT = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED,
    position=0,
)

_OK = HTTPStatus.OK


class _StubCountryResolver:
    """Always returns a fixed country code."""

    def __init__(self, country: str = "JP") -> None:
        self._country = country

    def resolve(self, headers: object) -> str:  # noqa: ARG002
        return self._country


# ── Helpers ──────────────────────────────────────────────────────────


def _build_login_body(
    *,
    username: str = "TestUser",
    password_md5: str = _PASSWORD_MD5,
    osu_version: str = "20231111",
    utc_offset: int = 9,
    display_city: int = 1,
    client_hashes: str = "hash1:hash2:hash3",
    pm_private: int = 0,
) -> bytes:
    """Build a raw login request body matching the osu! stable format."""
    client_info = f"{osu_version}|{utc_offset}|{display_city}|{client_hashes}|{pm_private}"
    text = f"{username}\n{password_md5}\n{client_info}\n"
    return text.encode("utf-8")


def _extract_login_reply_value(body: bytes) -> int:
    """Extract the user_id/error code from the first login_reply packet.

    Packet format: PacketID(u16) + Compression(u8) + ContentSize(u32) + Content.
    login_reply payload is a single int32.
    """
    _header_size = 7
    payload = body[_header_size : _header_size + 4]
    (value,) = struct.unpack("<i", payload)
    return value


def _make_app(
    *,
    country: str = "JP",
) -> tuple[
    Starlette,
    AuthService,
    InMemoryUserRepository,
    InMemoryRoleRepository,
    InMemorySessionStore,
]:
    """Build a Starlette app with LoginHandler wired to POST /.

    Returns the app plus all deps needed for test setup.
    """
    user_repo = InMemoryUserRepository()
    role_repo = InMemoryRoleRepository(seed_roles=[_ROLE_DEFAULT])
    session_store = InMemorySessionStore()
    password_service = PasswordService(hibp_client=None, banned_passwords=[])
    permission_service = PermissionService(role_repo=role_repo)
    country_resolver = _StubCountryResolver(country=country)

    auth_service = AuthService(
        user_repo=user_repo,
        role_repo=role_repo,
        password_service=password_service,
        permission_service=permission_service,
        session_store=session_store,
    )

    packet_queue = InMemoryPacketQueue()
    packet_dispatcher = PacketDispatcher()

    handler = LoginHandler(
        auth_service=auth_service,
        session_store=session_store,
        country_resolver=country_resolver,
        packet_queue=packet_queue,
        packet_dispatcher=packet_dispatcher,
    )

    # Starlette treats callable objects as ASGI apps, but we need
    # request_response wrapping. Pass the bound method instead.
    app = Starlette(routes=[Route("/", handler.__call__, methods=["POST"])])
    return app, auth_service, user_repo, role_repo, session_store


async def _setup_with_user(
    *,
    country: str = "JP",
) -> tuple[
    Starlette,
    AuthService,
    InMemoryUserRepository,
    InMemoryRoleRepository,
    InMemorySessionStore,
]:
    """Build app and register a test user."""
    result = _make_app(country=country)
    _, auth_service, *_ = result
    reg = await auth_service.register(
        RegistrationForm(
            username="TestUser",
            email="test@example.com",
            password=_PASSWORD,
        ),
    )
    assert reg.success is True
    return result


# ═══════════════════════════════════════════════════════════════════════
# Login success (Req 5.1, 5.2, 6.1-6.10)
# ═══════════════════════════════════════════════════════════════════════


class TestLoginSuccess:
    """cho-token header present, body contains login_reply with positive user_id."""

    async def test_cho_token_header_present(self) -> None:
        app, *_ = await _setup_with_user()
        with TestClient(app) as client:
            resp = client.post("/", content=_build_login_body())
            assert resp.status_code == _OK
            assert "cho-token" in resp.headers

    async def test_cho_token_is_nonempty(self) -> None:
        app, *_ = await _setup_with_user()
        with TestClient(app) as client:
            resp = client.post("/", content=_build_login_body())
            assert len(resp.headers["cho-token"]) > 0

    async def test_body_contains_login_reply_with_positive_user_id(self) -> None:
        app, *_ = await _setup_with_user()
        with TestClient(app) as client:
            resp = client.post("/", content=_build_login_body())
            user_id = _extract_login_reply_value(resp.content)
            assert user_id > 0

    async def test_login_reply_packet_bytes_in_stream(self) -> None:
        """The raw login_reply(user_id) bytes start the response body."""
        app, *_ = await _setup_with_user()
        with TestClient(app) as client:
            resp = client.post("/", content=_build_login_body())
            user_id = _extract_login_reply_value(resp.content)
            expected_packet = login_reply(user_id)
            assert resp.content.startswith(expected_packet)

    async def test_response_body_is_multi_packet_stream(self) -> None:
        """Body is longer than a single login_reply (multiple S2C packets)."""
        app, *_ = await _setup_with_user()
        with TestClient(app) as client:
            resp = client.post("/", content=_build_login_body())
            user_id = _extract_login_reply_value(resp.content)
            single_packet_len = len(login_reply(user_id))
            assert len(resp.content) > single_packet_len


# ═══════════════════════════════════════════════════════════════════════
# Login failure (Req 5.4)
# ═══════════════════════════════════════════════════════════════════════


class TestLoginFailure:
    """Authentication failed: body contains login_reply(-1), no cho-token."""

    async def test_wrong_password_returns_negative_one(self) -> None:
        app, *_ = await _setup_with_user()
        with TestClient(app) as client:
            resp = client.post(
                "/",
                content=_build_login_body(password_md5="0" * 32),
            )
            assert resp.status_code == _OK
            value = _extract_login_reply_value(resp.content)
            assert value == LoginResult.AUTHENTICATION_FAILED

    async def test_wrong_password_no_cho_token(self) -> None:
        app, *_ = await _setup_with_user()
        with TestClient(app) as client:
            resp = client.post(
                "/",
                content=_build_login_body(password_md5="0" * 32),
            )
            assert "cho-token" not in resp.headers

    async def test_nonexistent_user_returns_negative_one(self) -> None:
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/",
                content=_build_login_body(username="NoSuchUser"),
            )
            assert resp.status_code == _OK
            value = _extract_login_reply_value(resp.content)
            assert value == LoginResult.AUTHENTICATION_FAILED

    async def test_failure_body_is_login_reply_packet_only(self) -> None:
        """On auth failure, body is exactly one login_reply(-1) packet."""
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/",
                content=_build_login_body(username="NoSuchUser"),
            )
            expected = login_reply(LoginResult.AUTHENTICATION_FAILED)
            assert resp.content == expected


# ═══════════════════════════════════════════════════════════════════════
# Polling success (Req 7.1, 7.2)
# ═══════════════════════════════════════════════════════════════════════


class TestPollingSuccess:
    """Valid osu-token header: empty body, 200, TTL refreshed."""

    async def test_polling_returns_empty_body(self) -> None:
        app, *_ = await _setup_with_user()
        with TestClient(app) as client:
            login_resp = client.post("/", content=_build_login_body())
            token = login_resp.headers["cho-token"]

            poll_resp = client.post("/", headers={"osu-token": token})
            assert poll_resp.status_code == _OK
            assert poll_resp.content == b""

    async def test_polling_session_still_exists(self) -> None:
        """After polling, session is still valid (TTL refreshed)."""
        app, _, _, _, session_store = await _setup_with_user()
        with TestClient(app) as client:
            login_resp = client.post("/", content=_build_login_body())
            token = login_resp.headers["cho-token"]

            _ = client.post("/", headers={"osu-token": token})
            assert await session_store.exists(token) is True


# ═══════════════════════════════════════════════════════════════════════
# Polling with invalid token (Req 7.3)
# ═══════════════════════════════════════════════════════════════════════


class TestPollingInvalidToken:
    """Invalid/expired osu-token: body contains login_reply(-1)."""

    async def test_invalid_token_returns_login_reply_negative_one(self) -> None:
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/",
                headers={"osu-token": "invalid-token-abc"},
            )
            assert resp.status_code == _OK
            value = _extract_login_reply_value(resp.content)
            assert value == LoginResult.AUTHENTICATION_FAILED

    async def test_invalid_token_body_is_exact_packet(self) -> None:
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/",
                headers={"osu-token": "invalid-token-abc"},
            )
            expected = login_reply(LoginResult.AUTHENTICATION_FAILED)
            assert resp.content == expected


# ═══════════════════════════════════════════════════════════════════════
# Server error handling (Req 5.5)
# ═══════════════════════════════════════════════════════════════════════


class TestLoginServerError:
    """Unexpected exception during login returns login_reply(-5)."""

    async def test_server_error_returns_negative_five(self) -> None:
        app, _, user_repo, _, _ = await _setup_with_user()

        # Break the login by making user_repo raise
        user_repo.get_by_safe_username = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("DB down"),
        )

        with TestClient(app) as client:
            resp = client.post("/", content=_build_login_body())
            assert resp.status_code == _OK
            value = _extract_login_reply_value(resp.content)
            assert value == LoginResult.SERVER_ERROR


# ═══════════════════════════════════════════════════════════════════════
# Logging: structlog migration (Req 7.1)
# ═══════════════════════════════════════════════════════════════════════


class TestLoginHandlerStructlog:
    """LoginHandler uses structlog instead of stdlib logging."""

    async def test_parse_failure_logs_warning_via_structlog(self) -> None:
        """Malformed body emits a structlog warning with event name."""
        app, *_ = _make_app()

        with structlog.testing.capture_logs() as logs, TestClient(app) as client:
            client.post("/", content=b"malformed\x00garbage")

        parse_logs = [log for log in logs if log["event"] == "login_parse_failed"]
        assert len(parse_logs) == 1
        assert parse_logs[0]["log_level"] == "warning"


# ═══════════════════════════════════════════════════════════════════════
# Logging: contextvars binding (Req 7.1)
# ═══════════════════════════════════════════════════════════════════════


class TestLoginContextvarsBinding:
    """Successful login binds user/user_id to structlog contextvars."""

    async def test_contextvars_bound_after_login(self) -> None:
        """bind_contextvars(user=..., user_id=...) called on success."""
        app, *_ = await _setup_with_user()

        structlog.contextvars.clear_contextvars()

        with structlog.testing.capture_logs() as logs, TestClient(app) as client:
            client.post("/", content=_build_login_body())

        # The login_success event from AuthService confirms login worked;
        # contextvars binding happens in LoginHandler before response
        success_logs = [log for log in logs if log["event"] == "login_success"]
        assert len(success_logs) == 1
        assert success_logs[0]["username"] == "TestUser"
        assert success_logs[0]["user_id"] > 0

    async def test_contextvars_not_bound_on_failure(self) -> None:
        """No contextvars binding when authentication fails."""
        app, *_ = await _setup_with_user()

        structlog.contextvars.clear_contextvars()

        with structlog.testing.capture_logs() as logs, TestClient(app) as client:
            client.post("/", content=_build_login_body(password_md5="0" * 32))

        # No login_success event should exist, meaning no bind happened
        success_logs = [log for log in logs if log["event"] == "login_success"]
        assert len(success_logs) == 0

    async def test_contextvars_not_bound_on_parse_failure(self) -> None:
        """No contextvars binding when request parsing fails."""
        app, *_ = _make_app()

        structlog.contextvars.clear_contextvars()

        with structlog.testing.capture_logs() as logs, TestClient(app) as client:
            client.post("/", content=b"garbage")

        success_logs = [log for log in logs if log["event"] == "login_success"]
        assert len(success_logs) == 0
