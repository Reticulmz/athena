# pyright: reportAny=false
"""Tests for LifecycleListeners (UserDisconnected → USER_QUIT broadcast).

Validates:
- Req 6.3: All online users receive USER_QUIT packet via PacketQueue
- Req 6.3: Disconnecting user is excluded from broadcast
- Req 9.1: Unit tests with dependency mocks
- Edge case: Zero online users causes no error
"""

from __future__ import annotations

import struct
from unittest.mock import AsyncMock, call

import pytest

from osu_server.domain.users.events import UserDisconnected
from osu_server.transports.bancho.listeners.lifecycle import LifecycleListeners
from osu_server.transports.bancho.protocol.enums import ServerPacketID
from osu_server.transports.bancho.protocol.writer import write_packet


@pytest.fixture
def online_users() -> AsyncMock:
    """Mock OnlineUsersService."""
    mock = AsyncMock()
    mock.get_all_user_ids = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def packet_queue() -> AsyncMock:
    """Mock PacketQueue."""
    mock = AsyncMock()
    mock.enqueue = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def listeners(
    online_users: AsyncMock,
    packet_queue: AsyncMock,
) -> LifecycleListeners:
    """LifecycleListeners instance with mocked dependencies."""
    return LifecycleListeners(
        online_users=online_users,
        packet_queue=packet_queue,
    )


def _expected_user_quit_packet(user_id: int) -> bytes:
    """Build the expected USER_QUIT S2C packet for a given user_id."""
    return write_packet(ServerPacketID.USER_QUIT, struct.pack("<i", user_id))


class TestUserQuitBroadcast:
    """Req 6.3: USER_QUIT is enqueued to all online users."""

    async def test_all_online_users_receive_user_quit(
        self,
        listeners: LifecycleListeners,
        online_users: AsyncMock,
        packet_queue: AsyncMock,
    ) -> None:
        """Every online user (excluding the disconnecting one) gets USER_QUIT."""
        disconnecting_user_id = 100
        online_users.get_all_user_ids.return_value = [1, 2, 3, 100]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        expected_packet = _expected_user_quit_packet(disconnecting_user_id)
        packet_queue.enqueue.assert_any_await(1, expected_packet)
        packet_queue.enqueue.assert_any_await(2, expected_packet)
        packet_queue.enqueue.assert_any_await(3, expected_packet)
        assert packet_queue.enqueue.await_count == 3  # noqa: PLR2004

    async def test_disconnecting_user_excluded_from_broadcast(
        self,
        listeners: LifecycleListeners,
        online_users: AsyncMock,
        packet_queue: AsyncMock,
    ) -> None:
        """The disconnecting user must NOT receive their own USER_QUIT."""
        disconnecting_user_id = 42
        online_users.get_all_user_ids.return_value = [42, 99]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        expected_packet = _expected_user_quit_packet(disconnecting_user_id)
        # Only user 99 should receive the packet
        packet_queue.enqueue.assert_awaited_once_with(99, expected_packet)

    async def test_no_online_users_completes_without_error(
        self,
        listeners: LifecycleListeners,
        online_users: AsyncMock,
        packet_queue: AsyncMock,
    ) -> None:
        """Zero online users — handler completes without raising."""
        online_users.get_all_user_ids.return_value = []

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=1),
        )

        packet_queue.enqueue.assert_not_awaited()

    async def test_only_disconnecting_user_online_no_enqueue(
        self,
        listeners: LifecycleListeners,
        online_users: AsyncMock,
        packet_queue: AsyncMock,
    ) -> None:
        """When the only online user is the one disconnecting, no enqueue."""
        online_users.get_all_user_ids.return_value = [50]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=50),
        )

        packet_queue.enqueue.assert_not_awaited()


class TestUserQuitPacketFormat:
    """Verify USER_QUIT packet payload is int32 little-endian."""

    async def test_packet_contains_correct_user_id(
        self,
        listeners: LifecycleListeners,
        online_users: AsyncMock,
        packet_queue: AsyncMock,
    ) -> None:
        """USER_QUIT payload is the disconnecting user's ID as int32 LE."""
        disconnecting_user_id = 12345
        online_users.get_all_user_ids.return_value = [1]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        expected_packet = _expected_user_quit_packet(disconnecting_user_id)
        packet_queue.enqueue.assert_awaited_once_with(1, expected_packet)

        # Verify the raw payload structure: 7-byte header + 4-byte int32
        # Header: PacketID (u16) + Compression (u8) + ContentSize (u32)
        assert len(expected_packet) == 11  # noqa: PLR2004
        payload = expected_packet[7:]
        assert struct.unpack("<i", payload)[0] == disconnecting_user_id

    async def test_enqueue_call_order_matches_online_list(
        self,
        listeners: LifecycleListeners,
        online_users: AsyncMock,
        packet_queue: AsyncMock,
    ) -> None:
        """Enqueue calls follow the order of the online user list."""
        online_users.get_all_user_ids.return_value = [10, 20, 30]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=99),
        )

        expected_packet = _expected_user_quit_packet(99)
        assert packet_queue.enqueue.await_args_list == [
            call(10, expected_packet),
            call(20, expected_packet),
            call(30, expected_packet),
        ]
