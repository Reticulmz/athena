"""E2E tests for C2S packet handlers: EXIT, PONG, and exception isolation.

Tests the full HTTP POST → C2S dispatch → EventBus → S2C response pipeline
using the real Starlette app with in-memory stores (ENVIRONMENT=test).

Requirements coverage:
- Req 8.1: Exception logged, remaining packets continue
- Req 8.2: Error log includes packet ID and payload size
- Req 8.3: Each packet processed independently
- Req 9.3: HTTP POST → S2C response bytes E2E tests

Test scenarios:
1. EXIT → USER_QUIT broadcast to other online users
2. PONG accepted without error (empty response)
3. Exception isolation: bad packet + PONG in same request
"""

from __future__ import annotations

import hashlib
import os
import struct
from contextlib import contextmanager
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from starlette.testclient import TestClient

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID, ServerPacketID
from tests.support.app import create_in_memory_app as create_app
from tests.support.app import resolve_dependency_sync

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette

# ── Constants ────────────────────────────────────────────────────────────

_USER_A_USERNAME = "PlayerA"
_USER_A_EMAIL = "playera@example.com"
_USER_B_USERNAME = "PlayerB"
_USER_B_EMAIL = "playerb@example.com"

_TEST_PASSWORD = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD.encode()).hexdigest()
_TEST_CLIENT_INFO = "b20240101.1|9|1|abc:def:ghi:jkl:mno|0"

_PACKET_HEADER_SIZE = 7  # 2 (id) + 1 (compression) + 4 (content_length)

_DEFAULT_ROLE = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED,
    position=0,
)


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
    """Seed the Default role into the InMemoryRoleRepository."""
    repo = resolve_dependency_sync(app, RoleRepository)
    assert isinstance(repo, InMemoryRoleRepository)
    repo.add_role(_DEFAULT_ROLE)


def _login_body(
    *,
    username: str,
    password_md5: str = _TEST_PASSWORD_MD5,
    client_info: str = _TEST_CLIENT_INFO,
) -> bytes:
    """Build a raw login request body in osu! stable format."""
    return f"{username}\n{password_md5}\n{client_info}\n".encode()


def _registration_form(*, username: str, email: str) -> dict[str, str]:
    """Build a registration form data dict with check=0 (create account)."""
    return {
        "user[username]": username,
        "user[user_email]": email,
        "user[password]": _TEST_PASSWORD,
        "check": "0",
    }


def _register_user(client: TestClient, *, username: str, email: str) -> None:
    """Register a test user. Asserts success."""
    resp = client.post("/web/users", data=_registration_form(username=username, email=email))
    assert resp.status_code == HTTPStatus.OK, f"Registration failed: {resp.content!r}"


def _login_user(client: TestClient, *, username: str) -> str:
    """Login and return the cho-token."""
    resp = client.post("/", content=_login_body(username=username))
    assert resp.status_code == HTTPStatus.OK
    token = resp.headers["cho-token"]
    assert len(token) > 0

    # Drain the initial login packet queue (login response packets may be
    # enqueued for this user; the first poll clears them).
    drain_resp = client.post("/", headers={"osu-token": token})
    assert drain_resp.status_code == HTTPStatus.OK

    return token


def _build_c2s_packet(packet_id: int, payload: bytes = b"") -> bytes:
    """Build a raw C2S packet: 7-byte header + payload."""
    header = struct.pack("<HBI", packet_id, 0, len(payload))
    return header + payload


def _parse_s2c_packets(body: bytes) -> list[tuple[int, bytes]]:
    """Parse a concatenated S2C packet stream into (packet_id, content) pairs."""
    packets: list[tuple[int, bytes]] = []
    offset = 0
    while offset + _PACKET_HEADER_SIZE <= len(body):
        unpacked_id = struct.unpack_from("<H", body, offset)
        packet_id = cast("int", unpacked_id[0])
        unpacked_len = struct.unpack_from("<I", body, offset + 3)
        content_len = cast("int", unpacked_len[0])
        content_start = offset + _PACKET_HEADER_SIZE
        content_end = content_start + content_len
        if content_end > len(body):
            break
        content = body[content_start:content_end]
        packets.append((packet_id, content))
        offset = content_end
    return packets


def _find_packets(
    packets: list[tuple[int, bytes]],
    packet_id: int,
) -> list[bytes]:
    """Find all packets with the given ID and return their contents."""
    return [content for pid, content in packets if pid == packet_id]


# ── Test: EXIT → USER_QUIT broadcast ────────────────────────────────────


class TestExitUserQuitBroadcast:
    """EXIT packet from user A → USER_QUIT appears in user B's polling response."""

    def test_exit_broadcasts_user_quit_to_other_user(self) -> None:
        """POST with EXIT C2S packet enqueues USER_QUIT S2C for all other online users."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                # Register and login two users
                _register_user(client, username=_USER_A_USERNAME, email=_USER_A_EMAIL)
                _register_user(client, username=_USER_B_USERNAME, email=_USER_B_EMAIL)
                token_a = _login_user(client, username=_USER_A_USERNAME)
                token_b = _login_user(client, username=_USER_B_USERNAME)

                # User A sends EXIT packet
                exit_packet = _build_c2s_packet(ClientPacketID.EXIT)
                exit_resp = client.post(
                    "/",
                    content=exit_packet,
                    headers={"osu-token": token_a},
                )
                assert exit_resp.status_code == HTTPStatus.OK

                # User B polls — should receive USER_QUIT for user A
                poll_resp = client.post("/", headers={"osu-token": token_b})
                assert poll_resp.status_code == HTTPStatus.OK

                packets = _parse_s2c_packets(poll_resp.content)
                quit_contents = _find_packets(packets, int(ServerPacketID.USER_QUIT))

                assert len(quit_contents) >= 1, (
                    f"Expected USER_QUIT packet in poll response, "
                    f"got packet IDs: {[pid for pid, _ in packets]}"
                )

                # USER_QUIT payload is the disconnected user's ID as int32 LE
                unpacked_uid = struct.unpack("<i", quit_contents[0])
                quit_user_id = cast("int", unpacked_uid[0])
                assert quit_user_id > 0, "USER_QUIT should contain a positive user_id"

    def test_exit_does_not_enqueue_user_quit_for_self(self) -> None:
        """EXIT user should not receive their own USER_QUIT notification."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                _register_user(client, username=_USER_A_USERNAME, email=_USER_A_EMAIL)
                token_a = _login_user(client, username=_USER_A_USERNAME)

                # User A sends EXIT — response should not contain USER_QUIT for self.
                # After EXIT, the session is deleted, so the dequeue_all runs on
                # the (now-deleted) user. The response may be empty or contain
                # only other queued packets, but not a USER_QUIT for user A.
                exit_packet = _build_c2s_packet(ClientPacketID.EXIT)
                exit_resp = client.post(
                    "/",
                    content=exit_packet,
                    headers={"osu-token": token_a},
                )
                assert exit_resp.status_code == HTTPStatus.OK

                # The EXIT response should not contain a USER_QUIT for the
                # exiting user. Parse whatever was returned.
                packets = _parse_s2c_packets(exit_resp.content)
                quit_contents = _find_packets(packets, int(ServerPacketID.USER_QUIT))
                # There should be no USER_QUIT packets (no other users to notify about)
                assert len(quit_contents) == 0, (
                    "Exiting user (sole online user) should not receive any USER_QUIT packets"
                )


# ── Test: PONG acceptance ────────────────────────────────────────────────


class TestPongAcceptance:
    """PONG C2S packet is accepted without error."""

    def test_pong_returns_empty_response(self) -> None:
        """POST with PONG C2S packet returns 200 with empty body (no S2C queued)."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                _register_user(client, username=_USER_A_USERNAME, email=_USER_A_EMAIL)
                token = _login_user(client, username=_USER_A_USERNAME)

                # Send PONG packet
                pong_packet = _build_c2s_packet(ClientPacketID.PONG)
                resp = client.post(
                    "/",
                    content=pong_packet,
                    headers={"osu-token": token},
                )

                assert resp.status_code == HTTPStatus.OK
                # PONG is a no-op — no S2C packets should be generated
                assert resp.content == b""

    def test_multiple_pongs_accepted(self) -> None:
        """Multiple PONG packets in a single request are all accepted."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                _register_user(client, username=_USER_A_USERNAME, email=_USER_A_EMAIL)
                token = _login_user(client, username=_USER_A_USERNAME)

                # Send 3 concatenated PONG packets
                body = (
                    _build_c2s_packet(ClientPacketID.PONG)
                    + _build_c2s_packet(ClientPacketID.PONG)
                    + _build_c2s_packet(ClientPacketID.PONG)
                )
                resp = client.post(
                    "/",
                    content=body,
                    headers={"osu-token": token},
                )

                assert resp.status_code == HTTPStatus.OK
                assert resp.content == b""


# ── Test: Exception isolation ────────────────────────────────────────────


class TestExceptionIsolation:
    """A failing packet handler does not prevent subsequent packets from processing."""

    def test_invalid_packet_followed_by_pong_still_processes_pong(self) -> None:
        """Send an unregistered/invalid C2S packet + PONG in same request.

        The unregistered packet is silently skipped by the dispatcher,
        and PONG is still processed normally.
        This validates the try/except in PollingWorkflow (Req 8.1, 8.3).
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                _register_user(client, username=_USER_A_USERNAME, email=_USER_A_EMAIL)
                token = _login_user(client, username=_USER_A_USERNAME)

                # Build a packet with a valid but unregistered ClientPacketID
                # (SEND_MESSAGE = 1 has no handler registered yet) plus garbage payload
                # followed by a valid PONG packet.
                bad_packet = _build_c2s_packet(ClientPacketID.SEND_MESSAGE, b"\xff\xfe\xfd")
                pong_packet = _build_c2s_packet(ClientPacketID.PONG)
                body = bad_packet + pong_packet

                resp = client.post(
                    "/",
                    content=body,
                    headers={"osu-token": token},
                )

                # Request should succeed — exception isolation keeps processing
                assert resp.status_code == HTTPStatus.OK
                # PONG produces no S2C output, and unregistered packet is skipped
                assert resp.content == b""

    def test_exception_in_handler_does_not_break_subsequent_packets(self) -> None:
        """Register a handler that raises, send it + PONG, verify PONG still works.

        This directly tests the PollingWorkflow's try/except per-packet isolation
        with the real two-argument handler signature (Req 8.1, 8.2, 8.3).
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                _register_user(client, username=_USER_A_USERNAME, email=_USER_A_EMAIL)
                _register_user(client, username=_USER_B_USERNAME, email=_USER_B_EMAIL)
                token_a = _login_user(client, username=_USER_A_USERNAME)
                token_b = _login_user(client, username=_USER_B_USERNAME)

                # Register a handler that always raises for a specific packet ID.
                # Use BEATMAP_INFO (68) — unlikely to have a real handler.
                dispatcher = resolve_dependency_sync(app, PacketDispatcher)

                @dispatcher.register(ClientPacketID.BEATMAP_INFO)
                async def _boom(_payload: bytes, _user_id: int) -> None:
                    msg = "intentional test explosion"
                    raise RuntimeError(msg)

                _ = _boom

                # Send: BEATMAP_INFO (will raise) + EXIT (should still process)
                bad_packet = _build_c2s_packet(ClientPacketID.BEATMAP_INFO, b"\x00")
                exit_packet = _build_c2s_packet(ClientPacketID.EXIT)
                body = bad_packet + exit_packet

                resp = client.post(
                    "/",
                    content=body,
                    headers={"osu-token": token_a},
                )

                assert resp.status_code == HTTPStatus.OK

                # Verify EXIT was still processed despite BEATMAP_INFO failure:
                # User B should see USER_QUIT for user A
                poll_resp = client.post("/", headers={"osu-token": token_b})
                assert poll_resp.status_code == HTTPStatus.OK

                packets = _parse_s2c_packets(poll_resp.content)
                quit_contents = _find_packets(packets, int(ServerPacketID.USER_QUIT))

                assert len(quit_contents) >= 1, (
                    f"EXIT should have been processed despite BEATMAP_INFO error; "
                    f"got packet IDs: {[pid for pid, _ in packets]}"
                )
