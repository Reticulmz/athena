"""Tests for LifecycleListeners (UserDisconnected → USER_QUIT broadcast).

Validates:
- Req 6.3: All online users receive USER_QUIT packet via PacketQueue
- Req 6.3: Disconnecting user is excluded from broadcast
- Req 9.1: Unit tests with dependency mocks
- Edge case: Zero online users causes no error
"""

from __future__ import annotations

import struct
import typing

import pytest

from osu_server.domain.events.users import UserDisconnected
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue  # noqa: TC001
from osu_server.services.queries.identity import (
    ListActiveSessionsQuery,
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryResult,
    OnlineSessionSnapshot,
)
from osu_server.transports.stable.bancho.listeners.lifecycle import LifecycleListeners
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.writer import write_packet

BANCHO_PACKET_HEADER_SIZE = 7


def _snapshot(user_id: int) -> OnlineSessionSnapshot:
    return OnlineSessionSnapshot(
        user_id=user_id,
        username=f"user_{user_id}",
        privileges=0,
        country="JP",
        utc_offset=9,
    )


class FakeListActiveSessionsQuery:
    def __init__(self) -> None:
        self.user_ids: list[int] = []

    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult:
        _ = input_data
        return ListActiveSessionsQueryResult(
            sessions=tuple(_snapshot(user_id) for user_id in self.user_ids),
        )


class FakePacketQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[int, bytes]] = []

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        for packet in data:
            self.enqueued.append((user_id, packet))


@pytest.fixture
def online_users() -> FakeListActiveSessionsQuery:
    """Fake ListActiveSessionsQuery."""
    return FakeListActiveSessionsQuery()


@pytest.fixture
def packet_queue() -> FakePacketQueue:
    """Fake PacketQueue."""
    return FakePacketQueue()


@pytest.fixture
def listeners(
    online_users: FakeListActiveSessionsQuery,
    packet_queue: FakePacketQueue,
) -> LifecycleListeners:
    """LifecycleListeners instance with faked dependencies."""
    return LifecycleListeners(
        active_sessions_query=typing.cast(
            "ListActiveSessionsQuery", typing.cast("object", online_users)
        ),  # FakeListActiveSessionsQuery structurally compatible
        packet_queue=typing.cast(
            "PacketQueue", typing.cast("object", packet_queue)
        ),  # FakePacketQueue structurally compatible
    )


def _expected_user_quit_packet(user_id: int) -> bytes:
    """Build the expected USER_QUIT S2C packet for a given user_id."""
    return write_packet(ServerPacketID.USER_QUIT, struct.pack("<i", user_id))


class TestUserQuitBroadcast:
    """Req 6.3: USER_QUIT is enqueued to all online users."""

    async def test_all_online_users_receive_user_quit(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """Every online user (excluding the disconnecting one) gets USER_QUIT."""
        disconnecting_user_id = 100
        online_users.user_ids = [1, 2, 3, 100]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        expected_packet = _expected_user_quit_packet(disconnecting_user_id)
        assert (1, expected_packet) in packet_queue.enqueued
        assert (2, expected_packet) in packet_queue.enqueued
        assert (3, expected_packet) in packet_queue.enqueued
        assert len(packet_queue.enqueued) == 3

    async def test_disconnecting_user_excluded_from_broadcast(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """The disconnecting user must NOT receive their own USER_QUIT."""
        disconnecting_user_id = 42
        online_users.user_ids = [42, 99]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        expected_packet = _expected_user_quit_packet(disconnecting_user_id)
        assert (42, expected_packet) not in packet_queue.enqueued
        assert (99, expected_packet) in packet_queue.enqueued
        assert len(packet_queue.enqueued) == 1

    async def test_no_online_users_completes_without_error(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """Zero online users — handler completes without raising."""
        online_users.user_ids = []

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=1),
        )

        assert len(packet_queue.enqueued) == 0

    async def test_only_disconnecting_user_online_no_enqueue(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """When the only online user is the one disconnecting, no enqueue."""
        online_users.user_ids = [50]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=50),
        )

        assert len(packet_queue.enqueued) == 0


class TestUserQuitPacketFormat:
    """Verify USER_QUIT packet payload is int32 little-endian."""

    async def test_packet_contains_correct_user_id(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """USER_QUIT payload is the disconnecting user's ID as int32 LE."""
        disconnecting_user_id = 12345
        online_users.user_ids = [1]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        expected_packet = _expected_user_quit_packet(disconnecting_user_id)
        assert (1, expected_packet) in packet_queue.enqueued

        # Verify the raw payload structure: header + 4-byte int32
        payload = expected_packet[BANCHO_PACKET_HEADER_SIZE:]
        assert struct.unpack("<i", payload)[0] == disconnecting_user_id

    async def test_enqueue_call_order_matches_online_list(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """Enqueue calls follow the order of the online user list."""
        online_users.user_ids = [10, 20, 30]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=99),
        )

        expected_packet = _expected_user_quit_packet(99)
        assert packet_queue.enqueued == [
            (10, expected_packet),
            (20, expected_packet),
            (30, expected_packet),
        ]
