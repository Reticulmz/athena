"""Polling pipeline tests — C2S dispatch, S2C drain, error handling, logging.

Covers tasks 4.1, 4.2, 4.3 of the packet-polling spec.
"""

from __future__ import annotations

import hashlib
import struct
from http import HTTPStatus

import structlog.testing
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from osu_server.domain.auth import RegistrationForm
from osu_server.domain.role import Privileges, Role
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.auth_service import AuthService
from osu_server.services.channel_service import ChannelService
from osu_server.services.password_service import PasswordService
from osu_server.services.permission_service import PermissionService
from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.handlers.login import LoginHandler
from osu_server.transports.bancho.protocol.enums import ClientPacketID

# ── Constants ───────────────────────────────────────────────────────

_PASSWORD = "SecurePass1234"
_PASSWORD_MD5 = hashlib.md5(_PASSWORD.encode()).hexdigest()
_ROLE_DEFAULT = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED,
    position=0,
)
_OK = HTTPStatus.OK

# ── Helpers ─────────────────────────────────────────────────────────


class _StubCountryResolver:
    def resolve(self, headers: object) -> str:
        _ = headers
        return "JP"


def _make_empty_channel_service() -> ChannelService:
    return ChannelService(
        channel_repo=InMemoryChannelRepository(),
        channel_state=InMemoryChannelStateStore(),
    )


def _build_login_body(
    *,
    username: str = "TestUser",
    password_md5: str = _PASSWORD_MD5,
) -> bytes:
    client_info = "20231111|9|1|hash1:hash2:hash3|0"
    return f"{username}\n{password_md5}\n{client_info}\n".encode()


def _build_c2s_packet(packet_id: ClientPacketID, payload: bytes = b"") -> bytes:
    """Build a raw C2S packet (7-byte header + payload)."""
    return struct.pack("<HBI", packet_id.value, 0, len(payload)) + payload


def _make_polling_app(
    *,
    max_request_body_size: int = 1_048_576,
    session_ttl: int = 300,
) -> tuple[
    Starlette,
    AuthService,
    InMemorySessionStore,
    InMemoryPacketQueue,
    PacketDispatcher,
]:
    user_repo = InMemoryUserRepository()
    role_repo = InMemoryRoleRepository(seed_roles=[_ROLE_DEFAULT])
    session_store = InMemorySessionStore()
    packet_queue = InMemoryPacketQueue()
    packet_dispatcher = PacketDispatcher()

    auth_service = AuthService(
        user_repo=user_repo,
        role_repo=role_repo,
        password_service=PasswordService(hibp_client=None, banned_passwords=[]),
        permission_service=PermissionService(role_repo=role_repo),
        session_store=session_store,
    )

    handler = LoginHandler(
        auth_service=auth_service,
        session_store=session_store,
        country_resolver=_StubCountryResolver(),
        channel_service=_make_empty_channel_service(),
        packet_queue=packet_queue,
        packet_dispatcher=packet_dispatcher,
        session_ttl=session_ttl,
        max_request_body_size=max_request_body_size,
    )

    app = Starlette(routes=[Route("/", handler.__call__, methods=["POST"])])
    return app, auth_service, session_store, packet_queue, packet_dispatcher


async def _login(
    auth_service: AuthService,
    client: TestClient,
) -> str:
    """Register user, login, return token."""
    reg = await auth_service.register(
        RegistrationForm(username="TestUser", email="t@e.com", password=_PASSWORD),
    )
    assert reg.success is True
    resp = client.post("/", content=_build_login_body())
    assert resp.status_code == _OK
    return resp.headers["cho-token"]


# ═══════════════════════════════════════════════════════════════════
# Task 4.1: C2S→S2C Pipeline
# ═══════════════════════════════════════════════════════════════════


class TestC2SDispatch:
    """C2S packets are parsed and dispatched to registered handlers."""

    async def test_handler_called_with_payload(self) -> None:
        app, auth_service, _, _, dispatcher = _make_polling_app()
        called_with: list[bytes] = []

        @dispatcher.register(ClientPacketID.SEND_MESSAGE)
        async def handler(payload: bytes, *_a: object, **_kw: object) -> None:
            called_with.append(payload)

        _ = handler

        with TestClient(app) as client:
            token = await _login(auth_service, client)
            body = _build_c2s_packet(ClientPacketID.SEND_MESSAGE, b"\x01\x02")
            _ = client.post("/", headers={"osu-token": token}, content=body)

        assert len(called_with) == 1
        assert called_with[0] == b"\x01\x02"

    async def test_multiple_c2s_packets_dispatched_in_order(self) -> None:
        app, auth_service, _, _, dispatcher = _make_polling_app()
        order: list[str] = []

        @dispatcher.register(ClientPacketID.SEND_MESSAGE)
        async def on_msg(_payload: bytes, *_a: object, **_kw: object) -> None:
            order.append("msg")

        @dispatcher.register(ClientPacketID.JOIN_CHANNEL)
        async def on_join(_payload: bytes, *_a: object, **_kw: object) -> None:
            order.append("join")

        _ = (on_msg, on_join)

        with TestClient(app) as client:
            token = await _login(auth_service, client)
            body = _build_c2s_packet(ClientPacketID.JOIN_CHANNEL, b"\x00") + _build_c2s_packet(
                ClientPacketID.SEND_MESSAGE, b"\x00"
            )
            _ = client.post("/", headers={"osu-token": token}, content=body)

        assert order == ["join", "msg"]

    async def test_unregistered_packet_skipped(self) -> None:
        app, auth_service, _, _, dispatcher = _make_polling_app()
        called: list[str] = []

        @dispatcher.register(ClientPacketID.SEND_MESSAGE)
        async def handler(_payload: bytes, *_a: object, **_kw: object) -> None:
            called.append("msg")

        _ = handler

        with TestClient(app) as client:
            token = await _login(auth_service, client)
            body = _build_c2s_packet(ClientPacketID.PONG) + _build_c2s_packet(
                ClientPacketID.SEND_MESSAGE, b"\x00"
            )
            _ = client.post("/", headers={"osu-token": token}, content=body)

        assert called == ["msg"]


class TestS2CDrain:
    """S2C packets are drained from the queue and returned in the response."""

    async def test_queued_s2c_returned_in_response(self) -> None:
        app, auth_service, session_store, packet_queue, _ = _make_polling_app()

        with TestClient(app) as client:
            token = await _login(auth_service, client)

            # First poll activates queue
            _ = client.post("/", headers={"osu-token": token})

            # Enqueue S2C
            session = await session_store.get(token)
            assert session is not None
            user_id = session.user_id
            s2c_data = b"\xab\xcd\xef"
            await packet_queue.enqueue(user_id, s2c_data)

            # Second poll drains S2C
            resp = client.post("/", headers={"osu-token": token})
            assert resp.content == s2c_data

    async def test_empty_body_drains_s2c_only(self) -> None:
        app, auth_service, session_store, packet_queue, _ = _make_polling_app()

        with TestClient(app) as client:
            token = await _login(auth_service, client)
            _ = client.post("/", headers={"osu-token": token})

            session = await session_store.get(token)
            assert session is not None
            user_id = session.user_id
            await packet_queue.enqueue(user_id, b"\xff")

            resp = client.post("/", headers={"osu-token": token})
            assert resp.content == b"\xff"

    async def test_empty_queue_returns_empty_body(self) -> None:
        app, auth_service, _, _, _ = _make_polling_app()

        with TestClient(app) as client:
            token = await _login(auth_service, client)
            resp = client.post("/", headers={"osu-token": token})
            assert resp.content == b""


class TestC2SBeforeS2COrdering:
    """C2S handlers run before S2C drain (Req 2.4)."""

    async def test_handler_enqueued_s2c_appears_in_same_response(self) -> None:
        app, auth_service, session_store, packet_queue, dispatcher = _make_polling_app()
        user_id_holder: list[int] = []

        @dispatcher.register(ClientPacketID.SEND_MESSAGE)
        async def handler(_payload: bytes, *_a: object, **_kw: object) -> None:
            await packet_queue.enqueue(user_id_holder[0], b"\xde\xad")

        _ = handler

        with TestClient(app) as client:
            token = await _login(auth_service, client)
            # First poll to activate queue
            _ = client.post("/", headers={"osu-token": token})

            session = await session_store.get(token)
            assert session is not None
            user_id_holder.append(session.user_id)

            body = _build_c2s_packet(ClientPacketID.SEND_MESSAGE, b"\x00")
            resp = client.post("/", headers={"osu-token": token}, content=body)
            assert resp.content == b"\xde\xad"


# ═══════════════════════════════════════════════════════════════════
# Task 4.2: Error Handling
# ═══════════════════════════════════════════════════════════════════


class TestBodySizeLimit:
    """Oversized request body is rejected with empty response (Req 3.4)."""

    async def test_oversized_body_returns_empty(self) -> None:
        app, auth_service, _, _, _ = _make_polling_app(max_request_body_size=10)

        with TestClient(app) as client:
            token = await _login(auth_service, client)
            big_body = b"\x00" * 20
            resp = client.post("/", headers={"osu-token": token}, content=big_body)
            assert resp.content == b""

    async def test_oversized_body_skips_session_validation(self) -> None:
        """Oversized body returns empty even with invalid token."""
        app, _, _, _, _ = _make_polling_app(max_request_body_size=10)

        with TestClient(app) as client:
            big_body = b"\x00" * 20
            resp = client.post("/", headers={"osu-token": "invalid"}, content=big_body)
            # Empty response, NOT auth_failed
            assert resp.content == b""


class TestPacketReadError:
    """Malformed C2S data is caught; S2C drain still works (Req 3.1, 3.3)."""

    async def test_corrupt_body_still_drains_s2c(self) -> None:
        app, auth_service, session_store, packet_queue, _ = _make_polling_app()

        with TestClient(app) as client:
            token = await _login(auth_service, client)
            _ = client.post("/", headers={"osu-token": token})

            session = await session_store.get(token)
            assert session is not None
            user_id = session.user_id
            await packet_queue.enqueue(user_id, b"\xbe\xef")

            # Corrupt C2S body (too short for header)
            resp = client.post("/", headers={"osu-token": token}, content=b"\x01\x02")
            assert resp.content == b"\xbe\xef"


class TestHandlerException:
    """Handler exception is caught; subsequent packets still process (Req 3.2)."""

    async def test_exception_does_not_stop_subsequent_handlers(self) -> None:
        app, auth_service, _, _, dispatcher = _make_polling_app()
        results: list[str] = []

        @dispatcher.register(ClientPacketID.JOIN_CHANNEL)
        async def failing(_payload: bytes, *_a: object, **_kw: object) -> None:
            msg = "handler boom"
            raise RuntimeError(msg)

        @dispatcher.register(ClientPacketID.SEND_MESSAGE)
        async def succeeding(_payload: bytes, *_a: object, **_kw: object) -> None:
            results.append("ok")

        _ = (failing, succeeding)

        with TestClient(app) as client:
            token = await _login(auth_service, client)
            body = _build_c2s_packet(ClientPacketID.JOIN_CHANNEL, b"\x00") + _build_c2s_packet(
                ClientPacketID.SEND_MESSAGE, b"\x00"
            )
            _ = client.post("/", headers={"osu-token": token}, content=body)

        assert results == ["ok"]


# ═══════════════════════════════════════════════════════════════════
# Task 4.3: Structured Logging
# ═══════════════════════════════════════════════════════════════════


class TestPollingCompleteLog:
    """polling_complete event logged with c2s_count, s2c_bytes, elapsed_ms."""

    async def test_polling_complete_fields(self) -> None:
        app, auth_service, _, _, _ = _make_polling_app()

        with structlog.testing.capture_logs() as logs, TestClient(app) as client:
            token = await _login(auth_service, client)
            body = _build_c2s_packet(ClientPacketID.PONG)
            _ = client.post("/", headers={"osu-token": token}, content=body)

        poll_logs = [log for log in logs if log["event"] == "polling_complete"]
        assert len(poll_logs) >= 1
        log = poll_logs[-1]
        assert "c2s_count" in log
        assert "s2c_bytes" in log
        assert "elapsed_ms" in log
        assert log["c2s_count"] == 1
        assert log["s2c_bytes"] == 0


class TestParseErrorLog:
    """c2s_parse_error logged on malformed C2S data."""

    async def test_parse_error_logged(self) -> None:
        app, auth_service, _, _, _ = _make_polling_app()

        with structlog.testing.capture_logs() as logs, TestClient(app) as client:
            token = await _login(auth_service, client)
            _ = client.post("/", headers={"osu-token": token}, content=b"\x01\x02")

        parse_logs = [log for log in logs if log["event"] == "c2s_parse_error"]
        assert len(parse_logs) == 1
        assert parse_logs[0]["log_level"] == "error"


class TestHandlerErrorLog:
    """c2s_handler_error logged when a C2S handler throws."""

    async def test_handler_error_logged(self) -> None:
        app, auth_service, _, _, dispatcher = _make_polling_app()

        @dispatcher.register(ClientPacketID.SEND_MESSAGE)
        async def failing(_payload: bytes, *_a: object, **_kw: object) -> None:
            msg = "boom"
            raise RuntimeError(msg)

        _ = failing

        with structlog.testing.capture_logs() as logs, TestClient(app) as client:
            token = await _login(auth_service, client)
            body = _build_c2s_packet(ClientPacketID.SEND_MESSAGE, b"\x00")
            _ = client.post("/", headers={"osu-token": token}, content=body)

        error_logs = [log for log in logs if log["event"] == "c2s_handler_error"]
        assert len(error_logs) == 1
        assert error_logs[0]["log_level"] == "error"
        assert error_logs[0]["packet"] == "SEND_MESSAGE"
        assert "payload_size" in error_logs[0]
