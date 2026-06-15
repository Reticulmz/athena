"""E2E polling pipeline + edge case tests (Tasks 6.1, 6.2).

Tests the full login -> poll -> C2S dispatch -> S2C drain flow through
the refactored BanchoEndpoint + DI container.

Uses InMemoryPacketQueue for deterministic tests; Redis-specific
concurrent safety is tested in test_redis_packet_queue.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import struct
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from glide_shared.constants import TEncodable
    from starlette.applications import Starlette

import pytest
from starlette.testclient import TestClient

from osu_server.domain.identity.authentication import LoginResult, RegistrationForm
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.services.auth_service import AuthService
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from tests.support.app import create_in_memory_app, resolve_dependency

# -- Constants -----------------------------------------------------------

_PASSWORD = "SecurePass1234"
_PASSWORD_MD5 = hashlib.md5(_PASSWORD.encode()).hexdigest()
_ROLE_DEFAULT = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED,
    position=0,
)
_OK = HTTPStatus.OK
_HEADER_SIZE = 7

# Module-level env defaults for test DI container
_ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
_ = os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")


# -- Helpers --------------------------------------------------------------


def _build_login_body() -> bytes:
    client_info = "20231111|9|1|hash1:hash2:hash3|0"
    return f"TestUser\n{_PASSWORD_MD5}\n{client_info}\n".encode()


def _build_c2s_packet(packet_id: ClientPacketID, payload: bytes = b"") -> bytes:
    return struct.pack("<HBI", packet_id.value, 0, len(payload)) + payload


def _extract_login_reply(body: bytes) -> int:
    unpacked = struct.unpack("<i", body[_HEADER_SIZE : _HEADER_SIZE + 4])
    return cast("int", unpacked[0])


def _make_test_app(
    *,
    max_request_body_size: int = 1_048_576,
    packet_queue_max_size: int = 4096,
) -> Starlette:
    """Create the Starlette app with full DI container and BanchoEndpoint."""
    os.environ["ENVIRONMENT"] = "test"
    os.environ["MAX_REQUEST_BODY_SIZE"] = str(max_request_body_size)
    os.environ["PACKET_QUEUE_MAX_SIZE"] = str(packet_queue_max_size)
    return create_in_memory_app(packet_queue_max_size=packet_queue_max_size)


async def _seed_default_role(app: Starlette) -> None:
    """Seed the Default role into InMemoryRoleRepository after lifespan."""
    repo = await resolve_dependency(app, RoleRepository)
    assert isinstance(repo, InMemoryRoleRepository)
    repo.add_role(_ROLE_DEFAULT)


async def _resolve_services(
    app: Starlette,
) -> tuple[PacketDispatcher, PacketQueue, SessionStore, AuthService]:
    """Resolve test-facing services from the container after lifespan."""
    await _seed_default_role(app)
    return (
        await resolve_dependency(app, PacketDispatcher),
        await resolve_dependency(app, PacketQueue),
        await resolve_dependency(app, SessionStore),
        await resolve_dependency(app, AuthService),
    )


def _clear_dispatcher(dispatcher: PacketDispatcher) -> None:
    """Remove all registered handlers for test-isolated handler registration."""
    dispatcher._handlers.clear()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


async def _login_and_get_token(
    auth_service: AuthService,
    client: TestClient,
) -> str:
    _ = await auth_service.register(
        RegistrationForm(username="TestUser", email="t@e.com", password=_PASSWORD),
    )
    resp = client.post("/", content=_build_login_body())
    assert resp.status_code == _OK
    return resp.headers["cho-token"]


# ═══════════════════════════════════════════════════════════════════════
# Task 6.1: E2E Pipeline Tests
# ═══════════════════════════════════════════════════════════════════════


class TestPollingE2EFlow:
    """Login -> poll -> C2S -> S2C complete flow (Req 1.1, 2.1, 2.4)."""

    async def test_full_c2s_to_s2c_flow(self) -> None:
        """C2S handler enqueues S2C; S2C appears in same poll response."""
        app = _make_test_app()
        user_id_ref: list[int] = []

        with TestClient(app, raise_server_exceptions=False) as client:
            dispatcher, packet_queue, session_store, auth_service = await _resolve_services(app)

            _clear_dispatcher(dispatcher)

            @dispatcher.register(ClientPacketID.SEND_MESSAGE)
            async def handler(_payload: bytes, *_a: object, **_kw: object) -> None:
                await packet_queue.enqueue(user_id_ref[0], b"\xca\xfe")

            _ = handler

            token = await _login_and_get_token(auth_service, client)
            # First poll to activate queue
            _ = client.post("/", headers={"osu-token": token})

            session = await session_store.get(token)
            assert session is not None
            user_id_ref.append(session.user_id)

            # Second poll with C2S packet
            body = _build_c2s_packet(ClientPacketID.SEND_MESSAGE, b"\x01")
            resp = client.post("/", headers={"osu-token": token}, content=body)
            assert resp.content == b"\xca\xfe"


class TestSessionTTLRefresh:
    """Polling refreshes session TTL (Req 5.1)."""

    async def test_session_exists_after_poll(self) -> None:
        app = _make_test_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            _, _, session_store, auth_service = await _resolve_services(app)
            token = await _login_and_get_token(auth_service, client)
            _ = client.post("/", headers={"osu-token": token})
            assert await session_store.exists(token) is True


class TestInvalidTokenRejection:
    """Invalid token returns AUTH_FAILED (Req 6.1)."""

    async def test_invalid_token_returns_auth_failed(self) -> None:
        app = _make_test_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            _ = await _resolve_services(app)
            resp = client.post("/", headers={"osu-token": "bogus"})
            value = _extract_login_reply(resp.content)
            assert value == LoginResult.AUTHENTICATION_FAILED


class TestNoTokenFallsBackToLogin:
    """No osu-token header -> login flow (Req 6.2 regression)."""

    async def test_no_token_triggers_login(self) -> None:
        app = _make_test_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            _, _, _, auth_service = await _resolve_services(app)
            _ = await auth_service.register(
                RegistrationForm(
                    username="TestUser",
                    email="t@e.com",
                    password=_PASSWORD,
                ),
            )
            resp = client.post("/", content=_build_login_body())
            assert "cho-token" in resp.headers
            assert _extract_login_reply(resp.content) > 0


class TestBodySizeLimitE2E:
    """Oversized body skips processing (Req 3.4)."""

    async def test_oversized_body_returns_empty(self) -> None:
        app = _make_test_app(max_request_body_size=10)

        with TestClient(app, raise_server_exceptions=False) as client:
            _, _, _, auth_service = await _resolve_services(app)
            token = await _login_and_get_token(auth_service, client)
            resp = client.post(
                "/",
                headers={"osu-token": token},
                content=b"\x00" * 20,
            )
            assert resp.content == b""


# ═══════════════════════════════════════════════════════════════════════
# Task 6.2: Edge Cases and Concurrent Safety
# ═══════════════════════════════════════════════════════════════════════


class TestCorruptPacketEdgeCase:
    """Corrupt C2S header -> parse aborted, S2C drain still works (Req 3.1)."""

    async def test_corrupt_header_still_returns_s2c(self) -> None:
        app = _make_test_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            _, packet_queue, session_store, auth_service = await _resolve_services(app)
            token = await _login_and_get_token(auth_service, client)
            _ = client.post("/", headers={"osu-token": token})

            session = await session_store.get(token)
            assert session is not None
            user_id = session.user_id
            await packet_queue.enqueue(user_id, b"\xab")

            resp = client.post(
                "/",
                headers={"osu-token": token},
                content=b"\xff\xff",  # corrupt header
            )
            assert resp.content == b"\xab"


class TestHandlerExceptionEdgeCase:
    """Handler exception -> log + continue subsequent packets (Req 3.2)."""

    async def test_failing_handler_does_not_block_next(self) -> None:
        app = _make_test_app()
        results: list[str] = []

        with TestClient(app, raise_server_exceptions=False) as client:
            dispatcher, _, _, auth_service = await _resolve_services(app)

            _clear_dispatcher(dispatcher)

            @dispatcher.register(ClientPacketID.JOIN_CHANNEL)
            async def failing(_payload: bytes, *_a: object, **_kw: object) -> None:
                msg = "boom"
                raise RuntimeError(msg)

            @dispatcher.register(ClientPacketID.SEND_MESSAGE)
            async def ok(_payload: bytes, *_a: object, **_kw: object) -> None:
                results.append("ok")

            _ = (failing, ok)

            token = await _login_and_get_token(auth_service, client)
            body = _build_c2s_packet(
                ClientPacketID.JOIN_CHANNEL,
                b"\x00",
            ) + _build_c2s_packet(ClientPacketID.SEND_MESSAGE, b"\x00")
            _ = client.post("/", headers={"osu-token": token}, content=body)

        assert results == ["ok"]


class TestQueueSizeLimit:
    """Queue over max_size trims oldest packets (Req 4.2)."""

    async def test_oldest_trimmed_when_over_limit(self) -> None:
        app = _make_test_app(packet_queue_max_size=3)

        with TestClient(app, raise_server_exceptions=False) as client:
            _, packet_queue, session_store, auth_service = await _resolve_services(app)
            token = await _login_and_get_token(auth_service, client)
            _ = client.post("/", headers={"osu-token": token})

            session = await session_store.get(token)
            assert session is not None
            user_id = session.user_id

            for i in range(5):
                await packet_queue.enqueue(user_id, bytes([i]))

            resp = client.post("/", headers={"osu-token": token})
            assert resp.content == b"\x02\x03\x04"


class TestConcurrentDrainRedis:
    """Concurrent drain with Redis — no duplicate delivery (Req 1.3)."""

    @pytest.mark.skipif(
        not os.environ.get("VALKEY_URL"),
        reason="VALKEY_URL not set",
    )
    async def test_concurrent_drain_no_duplicates(self) -> None:
        from osu_server.infrastructure.cache.valkey_client import (
            create_valkey_client,
        )
        from osu_server.infrastructure.state.valkey.packet_queue import (
            ValkeyPacketQueue,
        )

        prefix = "athena_e2e_test:"
        valkey = await create_valkey_client(os.environ["VALKEY_URL"])
        try:
            queue = ValkeyPacketQueue(
                valkey,
                max_size=4096,
                ttl=300,
                key_prefix=prefix,
            )
            await queue.refresh_ttl(user_id=1, ttl=300)

            packet_count = 100
            for i in range(packet_count):
                await queue.enqueue(1, bytes([i % 256]))

            results = await asyncio.gather(
                queue.dequeue_all(user_id=1),
                queue.dequeue_all(user_id=1),
                queue.dequeue_all(user_id=1),
            )

            non_empty = [r for r in results if r != b""]
            assert len(non_empty) == 1
            assert len(non_empty[0]) == packet_count
        finally:
            for pattern in (f"{prefix}packet_queue:*", f"{prefix}pq_meta:*"):
                cursor: str = "0"
                while True:
                    next_cursor, keys = await valkey.scan(
                        cursor,
                        match=pattern,
                        count=100,
                    )
                    if keys:
                        _ = await valkey.delete(cast("list[TEncodable]", keys))
                    cursor = (
                        next_cursor.decode()
                        if isinstance(next_cursor, bytes)
                        else str(next_cursor)
                    )
                    if cursor == "0":
                        break
            await valkey.close()
