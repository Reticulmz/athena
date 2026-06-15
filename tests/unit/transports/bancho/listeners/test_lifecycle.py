"""Tests for LifecycleListeners — BanchoBot exclusion from USER_QUIT fan-out.

Validates:
- Req 3.3: BanchoBot is never a USER_QUIT fan-out target
- Req 3.4: LifecycleListeners uses ListOnlineUsersQuery, which returns active
  session IDs only — BanchoBot has no SessionData
"""

from __future__ import annotations

import struct
import typing

import pytest

from osu_server.domain.events.users import UserDisconnected
from osu_server.domain.system_user import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue  # noqa: TC001
from osu_server.services.queries.identity import (
    ListOnlineUsersQuery,
    ListOnlineUsersQueryInput,
    ListOnlineUsersQueryResult,
)
from osu_server.transports.stable.bancho.listeners.lifecycle import LifecycleListeners
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.writer import write_packet


class FakeListOnlineUsersQuery:
    """Fake query that returns configurable user IDs (no BanchoBot)."""

    def __init__(self) -> None:
        self.user_ids: list[int] = []

    async def execute(self, input_data: ListOnlineUsersQueryInput) -> ListOnlineUsersQueryResult:
        _ = input_data
        return ListOnlineUsersQueryResult(user_ids=tuple(self.user_ids))


class FakePacketQueue:
    """Fake that records enqueued (user_id, packet) pairs."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[int, bytes]] = []

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        for packet in data:
            self.enqueued.append((user_id, packet))


@pytest.fixture
def online_users() -> FakeListOnlineUsersQuery:
    """Fake ListOnlineUsersQuery."""
    return FakeListOnlineUsersQuery()


@pytest.fixture
def packet_queue() -> FakePacketQueue:
    """Fake PacketQueue."""
    return FakePacketQueue()


@pytest.fixture
def listeners(
    online_users: FakeListOnlineUsersQuery,
    packet_queue: FakePacketQueue,
) -> LifecycleListeners:
    """LifecycleListeners instance with faked dependencies."""
    return LifecycleListeners(
        online_users_query=typing.cast(
            "ListOnlineUsersQuery",
            typing.cast("object", online_users),
        ),
        packet_queue=typing.cast("PacketQueue", typing.cast("object", packet_queue)),
    )


def _expected_user_quit_packet(user_id: int) -> bytes:
    """Build the expected USER_QUIT S2C packet for a given user_id."""
    return write_packet(ServerPacketID.USER_QUIT, struct.pack("<i", user_id))


class TestBanchoBotNotInUserQuitFanOut:
    """Req 3.3, 3.4: USER_QUIT fan-out excludes BanchoBot.

    LifecycleListeners uses ListOnlineUsersQuery to determine
    USER_QUIT broadcast targets.  Since BanchoBot has no SessionData and is not
    an active session, get_all_user_ids() never returns BanchoBot's ID.
    LifecycleListeners therefore never enqueues USER_QUIT for BanchoBot.
    """

    async def test_banchobot_not_in_fanout_with_multiple_users(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListOnlineUsersQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """BanchoBot ID is not among USER_QUIT recipients when multiple humans are online."""
        disconnecting_user_id = 100
        # Active session IDs — BanchoBot (user_id=1) is not a session
        online_users.user_ids = [2, 3, 42, 100]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        target_ids = [uid for uid, _ in packet_queue.enqueued]
        assert BANCHO_BOT_IDENTITY.user_id not in target_ids
        # Only human users excluding the disconnecting one
        assert set(target_ids) == {2, 3, 42}
        assert len(packet_queue.enqueued) == 3

    async def test_banchobot_not_in_fanout_with_single_user(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListOnlineUsersQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """BanchoBot is not targeted even when only one other human is online."""
        disconnecting_user_id = 50
        online_users.user_ids = [50, 99]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        target_ids = [uid for uid, _ in packet_queue.enqueued]
        assert BANCHO_BOT_IDENTITY.user_id not in target_ids
        assert target_ids == [99]
        assert len(packet_queue.enqueued) == 1

    async def test_banchobot_not_in_fanout_no_other_users(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListOnlineUsersQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """No fan-out when only the disconnecting user is online -- BanchoBot not involved."""
        online_users.user_ids = [50]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=50),
        )

        target_ids = [uid for uid, _ in packet_queue.enqueued]
        assert BANCHO_BOT_IDENTITY.user_id not in target_ids
        assert len(packet_queue.enqueued) == 0

    async def test_banchobot_exclusion_preserves_user_quit_packet_format(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListOnlineUsersQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """USER_QUIT packets sent to humans have the correct format (user_id payload)."""
        disconnecting_user_id = 77
        online_users.user_ids = [2, 77]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        expected_packet = _expected_user_quit_packet(disconnecting_user_id)
        assert packet_queue.enqueued == [(2, expected_packet)]
        # No entry for BanchoBot
        assert BANCHO_BOT_IDENTITY.user_id not in [uid for uid, _ in packet_queue.enqueued]


class TestBanchoBotSessionSeparationContract:
    """Req 3.4: LifecycleListeners depends on ListOnlineUsersQuery for active session IDs.

    BanchoBot is roster-visible but not an active session.  The separation is:
    - ListOnlineUsersQuery → SessionStore active sessions
    - BanchoBot identity → LoginResponseBuilder roster packets only
    - No crossover: BanchoBot never flows through the lifecycle fan-out path
    """

    async def test_fan_out_uses_online_users_service_exclusively(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListOnlineUsersQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """LifecycleListeners only fans out to IDs returned by ListOnlineUsersQuery."""
        online_users.user_ids = [10, 20, 30]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=10),
        )

        # All enqueued targets come from ListOnlineUsersQuery
        target_ids = {uid for uid, _ in packet_queue.enqueued}
        assert target_ids == {20, 30}
        assert BANCHO_BOT_IDENTITY.user_id not in target_ids

    async def test_no_banchobot_leakage_from_empty_online_list(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListOnlineUsersQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """When no users are online, no fan-out occurs and BanchoBot is never added."""
        online_users.user_ids = []

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=42),
        )

        assert len(packet_queue.enqueued) == 0
        # Even in empty state, BanchoBot is never enqueued
        assert BANCHO_BOT_IDENTITY.user_id not in [uid for uid, _ in packet_queue.enqueued]
