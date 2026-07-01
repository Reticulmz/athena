from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.state.memory.stable_user_status_store import (
    InMemoryStableUserStatusStore,
)
from osu_server.services.queries.identity import (
    GetActiveSessionsByUserIdsQuery,
    GetActiveSessionsByUserIdsQueryInput,
    GetActiveSessionsByUserIdsQueryResult,
    ListActiveSessionsQuery,
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryResult,
    OnlineSessionSnapshot,
)
from osu_server.transports.stable.bancho.handlers.presence import PresenceHandlers
from osu_server.transports.stable.bancho.mappers.presence import (
    bot_presence_packet,
    online_session_presence_packet,
    online_session_presence_packet_for_mode,
)
from osu_server.transports.stable.bancho.protocol.c2s import presence_request_payload
from osu_server.transports.stable.bancho.protocol.s2c.login import user_presence_bundle

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue


@final
class FakeListActiveSessionsQuery:
    def __init__(self, sessions: tuple[OnlineSessionSnapshot, ...]) -> None:
        self._sessions = sessions
        self.calls = 0

    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult:
        assert isinstance(input_data, ListActiveSessionsQueryInput)
        self.calls += 1
        return ListActiveSessionsQueryResult(sessions=self._sessions)


@final
class FakeGetActiveSessionsByUserIdsQuery:
    def __init__(self, sessions: tuple[OnlineSessionSnapshot, ...]) -> None:
        self._sessions_by_user_id = {session.user_id: session for session in sessions}
        self.inputs: list[tuple[int, ...]] = []

    async def execute(
        self,
        input_data: GetActiveSessionsByUserIdsQueryInput,
    ) -> GetActiveSessionsByUserIdsQueryResult:
        assert isinstance(input_data, GetActiveSessionsByUserIdsQueryInput)
        self.inputs.append(input_data.user_ids)
        return GetActiveSessionsByUserIdsQueryResult(
            sessions=tuple(
                self._sessions_by_user_id[user_id]
                for user_id in input_data.user_ids
                if user_id in self._sessions_by_user_id
            )
        )


@final
class FakePacketQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[int, tuple[bytes, ...]]] = []

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        self.enqueued.append((user_id, data))

    async def dequeue_all(self, user_id: int) -> bytes:
        _ = user_id
        return b""

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        _ = (user_id, ttl)


async def test_presence_request_returns_requested_online_user_presence() -> None:
    online = (_snapshot(20), _snapshot(30))
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeListActiveSessionsQuery(online)
    active_sessions_by_user_ids_query = FakeGetActiveSessionsByUserIdsQuery(online)
    handlers = _handlers(
        active_sessions_query,
        active_sessions_by_user_ids_query,
        packet_queue,
    )

    await handlers.handle_presence_request(
        presence_request_payload([30, BANCHO_BOT_IDENTITY.user_id, 20, 99]),
        user_id=3,
    )

    assert packet_queue.enqueued == [
        (
            3,
            (
                online_session_presence_packet(online[1]),
                bot_presence_packet(),
                online_session_presence_packet(online[0]),
            ),
        )
    ]
    assert active_sessions_query.calls == 0
    assert active_sessions_by_user_ids_query.inputs == [(30, 20, 99)]


async def test_presence_request_drops_malformed_payload_without_enqueue() -> None:
    packet_queue = FakePacketQueue()
    handlers = _handlers(
        FakeListActiveSessionsQuery((_snapshot(20),)),
        FakeGetActiveSessionsByUserIdsQuery((_snapshot(20),)),
        packet_queue,
    )

    await handlers.handle_presence_request(b"\x00", user_id=3)

    assert packet_queue.enqueued == []


async def test_presence_request_all_accepts_bancho_py_reserved_int32_payload() -> None:
    online = (_snapshot(20), _snapshot(30))
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeListActiveSessionsQuery(online)
    active_sessions_by_user_ids_query = FakeGetActiveSessionsByUserIdsQuery(online)
    handlers = _handlers(
        active_sessions_query,
        active_sessions_by_user_ids_query,
        packet_queue,
    )

    await handlers.handle_presence_request_all(b"\x00\x00\x00\x00", user_id=3)

    assert packet_queue.enqueued == [
        (
            3,
            (
                bot_presence_packet(),
                online_session_presence_packet(online[0]),
                online_session_presence_packet(online[1]),
                user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, 20, 30]),
            ),
        )
    ]
    assert active_sessions_query.calls == 1
    assert active_sessions_by_user_ids_query.inputs == []


async def test_presence_request_uses_target_user_current_mode() -> None:
    online = (_snapshot(20), _snapshot(30))
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeListActiveSessionsQuery(online)
    active_sessions_by_user_ids_query = FakeGetActiveSessionsByUserIdsQuery(online)
    status_store = InMemoryStableUserStatusStore()
    await status_store.set_play_mode(20, 3)
    handlers = _handlers(
        active_sessions_query,
        active_sessions_by_user_ids_query,
        packet_queue,
        stable_user_status_store=status_store,
    )

    await handlers.handle_presence_request(
        presence_request_payload([20, 30]),
        user_id=3,
    )

    assert packet_queue.enqueued == [
        (
            3,
            (
                online_session_presence_packet_for_mode(online[0], play_mode=3),
                online_session_presence_packet(online[1]),
            ),
        )
    ]
    assert active_sessions_query.calls == 0
    assert active_sessions_by_user_ids_query.inputs == [(20, 30)]


async def test_presence_request_uses_requester_current_mode_for_bot() -> None:
    online = (_snapshot(20),)
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeListActiveSessionsQuery(online)
    active_sessions_by_user_ids_query = FakeGetActiveSessionsByUserIdsQuery(online)
    status_store = InMemoryStableUserStatusStore()
    await status_store.set_play_mode(3, 3)
    handlers = _handlers(
        active_sessions_query,
        active_sessions_by_user_ids_query,
        packet_queue,
        stable_user_status_store=status_store,
    )

    await handlers.handle_presence_request(
        presence_request_payload([BANCHO_BOT_IDENTITY.user_id]),
        user_id=3,
    )

    assert packet_queue.enqueued == [
        (
            3,
            (bot_presence_packet(play_mode=3),),
        )
    ]
    assert active_sessions_query.calls == 0
    assert active_sessions_by_user_ids_query.inputs == [()]


async def test_presence_request_all_uses_target_user_current_modes_for_roster() -> None:
    online = (_snapshot(20), _snapshot(30))
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeListActiveSessionsQuery(online)
    active_sessions_by_user_ids_query = FakeGetActiveSessionsByUserIdsQuery(online)
    status_store = InMemoryStableUserStatusStore()
    await status_store.set_play_mode(20, 3)
    handlers = _handlers(
        active_sessions_query,
        active_sessions_by_user_ids_query,
        packet_queue,
        stable_user_status_store=status_store,
    )

    await handlers.handle_presence_request_all(b"\x00\x00\x00\x00", user_id=3)

    assert packet_queue.enqueued == [
        (
            3,
            (
                bot_presence_packet(),
                online_session_presence_packet_for_mode(online[0], play_mode=3),
                online_session_presence_packet(online[1]),
                user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, 20, 30]),
            ),
        )
    ]
    assert active_sessions_query.calls == 1
    assert active_sessions_by_user_ids_query.inputs == []


async def test_presence_request_all_uses_requester_current_mode_for_bot() -> None:
    online = (_snapshot(20),)
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeListActiveSessionsQuery(online)
    active_sessions_by_user_ids_query = FakeGetActiveSessionsByUserIdsQuery(online)
    status_store = InMemoryStableUserStatusStore()
    await status_store.set_play_mode(3, 3)
    handlers = _handlers(
        active_sessions_query,
        active_sessions_by_user_ids_query,
        packet_queue,
        stable_user_status_store=status_store,
    )

    await handlers.handle_presence_request_all(b"\x00\x00\x00\x00", user_id=3)

    assert packet_queue.enqueued == [
        (
            3,
            (
                bot_presence_packet(play_mode=3),
                online_session_presence_packet(online[0]),
                user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, 20]),
            ),
        )
    ]
    assert active_sessions_query.calls == 1
    assert active_sessions_by_user_ids_query.inputs == []


async def test_presence_request_all_drops_unknown_payload_size() -> None:
    packet_queue = FakePacketQueue()
    handlers = _handlers(
        FakeListActiveSessionsQuery((_snapshot(20),)),
        FakeGetActiveSessionsByUserIdsQuery((_snapshot(20),)),
        packet_queue,
    )

    await handlers.handle_presence_request_all(b"\x00", user_id=3)

    assert packet_queue.enqueued == []


def _handlers(
    active_sessions_query: FakeListActiveSessionsQuery,
    active_sessions_by_user_ids_query: FakeGetActiveSessionsByUserIdsQuery,
    packet_queue: FakePacketQueue,
    *,
    stable_user_status_store: InMemoryStableUserStatusStore | None = None,
) -> PresenceHandlers:
    return PresenceHandlers(
        active_sessions_query=cast(
            "ListActiveSessionsQuery",
            active_sessions_query,
        ),
        active_sessions_by_user_ids_query=cast(
            "GetActiveSessionsByUserIdsQuery",
            active_sessions_by_user_ids_query,
        ),
        packet_queue=cast("PacketQueue", packet_queue),
        stable_user_status_store=stable_user_status_store,
    )


def _snapshot(
    user_id: int,
    *,
    username: str | None = None,
    privileges: int = 0,
) -> OnlineSessionSnapshot:
    return OnlineSessionSnapshot(
        user_id=user_id,
        username=username or f"user_{user_id}",
        privileges=privileges,
        country="JP",
        utc_offset=9,
    )
