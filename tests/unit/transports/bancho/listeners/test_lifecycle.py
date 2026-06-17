"""Tests for LifecycleListeners — BanchoBot exclusion from USER_QUIT fan-out.

Validates:
- Req 3.3: BanchoBot is never a USER_QUIT fan-out target
- Req 3.4: LifecycleListeners uses ListActiveSessionsQuery, which returns active
  session IDs only — BanchoBot has no SessionData
"""

from __future__ import annotations

import struct
import typing

import pytest

from osu_server.domain.compatibility.stable.permissions import BanchoClientPermission
from osu_server.domain.events.users import UserConnected, UserDisconnected
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue  # noqa: TC001
from osu_server.services.queries.identity import (
    ListActiveSessionsQuery,
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryResult,
    OnlineSessionSnapshot,
)
from osu_server.transports.stable.bancho.listeners.lifecycle import LifecycleListeners
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import user_presence
from osu_server.transports.stable.bancho.protocol.writer import write_packet


def _snapshot(user_id: int) -> OnlineSessionSnapshot:
    return OnlineSessionSnapshot(
        user_id=user_id,
        username=f"user_{user_id}",
        privileges=0,
        country="JP",
        utc_offset=9,
    )


class FakeListActiveSessionsQuery:
    """Fake query that returns configurable user IDs (no BanchoBot)."""

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
    """Fake that records enqueued (user_id, packet) pairs."""

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
            "ListActiveSessionsQuery",
            typing.cast("object", online_users),
        ),
        packet_queue=typing.cast("PacketQueue", typing.cast("object", packet_queue)),
    )


def _expected_user_quit_packet(user_id: int) -> bytes:
    """Build the expected USER_QUIT S2C packet for a given user_id."""
    return write_packet(ServerPacketID.USER_QUIT, struct.pack("<i", user_id))


def _expected_user_presence_packet(session: OnlineSessionSnapshot) -> bytes:
    """Build the expected USER_PRESENCE S2C packet for an online session."""
    return user_presence(
        user_id=session.user_id,
        username=session.username,
        timezone=session.utc_offset + 24,
        country_id=country_code_to_id(session.country),
        permissions=int(BanchoClientPermission.NORMAL),
        mode=0,
        longitude=0.0,
        latitude=0.0,
        rank=0,
    )


class TestUserPresenceBroadcast:
    """UserConnected fan-out sends USER_PRESENCE to existing active sessions."""

    async def test_connected_user_presence_broadcasts_to_other_online_users(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """Every other online user receives the newly connected user's USER_PRESENCE."""
        connected_user_id = 20
        online_users.user_ids = [10, connected_user_id, 30]

        await listeners.on_user_connected(UserConnected(user_id=connected_user_id))

        expected_packet = _expected_user_presence_packet(_snapshot(connected_user_id))
        assert packet_queue.enqueued == [
            (10, expected_packet),
            (30, expected_packet),
        ]

    async def test_connected_user_does_not_receive_own_presence_broadcast(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """The newly connected user's queue is excluded from live presence fan-out."""
        connected_user_id = 42
        online_users.user_ids = [connected_user_id, 99]

        await listeners.on_user_connected(UserConnected(user_id=connected_user_id))

        target_ids = [uid for uid, _ in packet_queue.enqueued]
        assert connected_user_id not in target_ids
        assert target_ids == [99]

    async def test_connected_event_without_active_session_is_noop(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """No USER_PRESENCE is sent if the connected user's session is absent."""
        online_users.user_ids = [10, 30]

        await listeners.on_user_connected(UserConnected(user_id=20))

        assert packet_queue.enqueued == []

    async def test_only_connected_user_online_no_presence_broadcast(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """No fan-out occurs when the connected user is the only active session."""
        online_users.user_ids = [20]

        await listeners.on_user_connected(UserConnected(user_id=20))

        assert packet_queue.enqueued == []


class TestBanchoBotNotInUserQuitFanOut:
    """Req 3.3, 3.4: USER_QUIT fan-out excludes BanchoBot.

    LifecycleListeners uses ListActiveSessionsQuery to determine
    USER_QUIT broadcast targets.  Since BanchoBot has no SessionData and is not
    an active session, the query result never returns BanchoBot's ID.
    LifecycleListeners therefore never enqueues USER_QUIT for BanchoBot.
    """

    async def test_banchobot_not_in_fanout_with_multiple_users(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
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
        online_users: FakeListActiveSessionsQuery,
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
        online_users: FakeListActiveSessionsQuery,
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
        online_users: FakeListActiveSessionsQuery,
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
    """Req 3.4: LifecycleListeners depends on ListActiveSessionsQuery for active session IDs.

    BanchoBot is roster-visible but not an active session.  The separation is:
    - ListActiveSessionsQuery -> SessionStore active sessions
    - BanchoBot identity → LoginResponseBuilder roster packets only
    - No crossover: BanchoBot never flows through the lifecycle fan-out path
    """

    async def test_fan_out_uses_active_session_query_exclusively(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """LifecycleListeners only fans out to active session query results."""
        online_users.user_ids = [10, 20, 30]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=10),
        )

        # All enqueued targets come from ListActiveSessionsQuery
        target_ids = {uid for uid, _ in packet_queue.enqueued}
        assert target_ids == {20, 30}
        assert BANCHO_BOT_IDENTITY.user_id not in target_ids

    async def test_no_banchobot_leakage_from_empty_online_list(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
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
