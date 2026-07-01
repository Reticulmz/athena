"""Tests for STATUS_CHANGE beatmap file warmup handling."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, final

import structlog.testing

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapResolveOptions,
    BeatmapResolveResult,
)
from osu_server.domain.compatibility.stable import StableUserStatus
from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import UserPerformanceBest
from osu_server.repositories.interfaces.queries.user_stats import (
    UserStatsRankInput,
    UserStatsSourceRead,
    UserStatsSourceRow,
)
from osu_server.services.commands.beatmaps import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupOutcome,
    BeatmapFileWarmupRequest,
    BeatmapFileWarmupResult,
    RequestBeatmapFileWarmupUseCase,
)
from osu_server.services.queries.identity import (
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryResult,
    OnlineSessionSnapshot,
)
from osu_server.services.queries.scores import (
    CurrentUserStatsQuery,
    CurrentUserStatsQueryInput,
)
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.handlers.status import StatusChangeHandlers
from osu_server.transports.stable.bancho.protocol.c2s import status_change_payload
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import user_stats
from osu_server.transports.stable.bancho.protocol.types import StatusUpdate

if TYPE_CHECKING:
    from structlog.typing import EventDict

_USER_ID = 42
_CHECKSUM = "3b0aecd99eba50ffc7bff8da117d0e06"


@final
class RecordingWarmupUseCase:
    def __init__(self) -> None:
        self.requests: list[BeatmapFileWarmupRequest] = []
        self.raise_on_execute: Exception | None = None

    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult:
        self.requests.append(request)
        if self.raise_on_execute is not None:
            raise self.raise_on_execute
        return BeatmapFileWarmupResult(
            outcome=BeatmapFileWarmupOutcome.REQUESTED,
            entrance=request.entrance,
            user_id=request.user_id,
            beatmap_id=request.beatmap_id,
            checksum_md5=request.checksum_md5,
            reason="recorded",
        )


@final
class RecordingStableUserStatusStore:
    def __init__(self) -> None:
        self.statuses: list[tuple[int, StableUserStatus]] = []
        self.play_modes: list[tuple[int, int]] = []

    async def set_status(self, user_id: int, status: StableUserStatus) -> None:
        self.statuses.append((user_id, status))
        self.play_modes.append((user_id, status.play_mode))

    async def get_statuses(
        self,
        user_ids: tuple[int, ...],
    ) -> dict[int, StableUserStatus]:
        return {
            user_id: status
            for stored_user_id, status in self.statuses
            if stored_user_id in user_ids
            for user_id in (stored_user_id,)
        }

    async def set_play_mode(self, user_id: int, play_mode: int) -> None:
        self.play_modes.append((user_id, play_mode))

    async def get_play_mode(self, user_id: int) -> int | None:
        _ = user_id
        return None

    async def get_play_modes(self, user_ids: tuple[int, ...]) -> dict[int, int]:
        _ = user_ids
        return {}

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        _ = (user_id, ttl)


@final
class RecordingUserStatsQueryRepository:
    def __init__(self) -> None:
        self.inputs: list[CurrentUserStatsQueryInput] = []

    async def read_current_stats_sources(
        self,
        user_ids: tuple[int, ...],
        *,
        ruleset: Ruleset = Ruleset.OSU,
        playstyle: Playstyle = Playstyle.VANILLA,
    ) -> UserStatsSourceRead:
        self.inputs.append(
            CurrentUserStatsQueryInput(
                user_ids=user_ids,
                ruleset=ruleset,
                playstyle=playstyle,
            )
        )
        return UserStatsSourceRead(
            users=(
                UserStatsSourceRow(
                    user_id=_USER_ID,
                    play_count=5,
                    ranked_score=900_000,
                    total_score=900_000,
                    play_time_seconds=None,
                    best_performances=(UserPerformanceBest(pp=Decimal("250"), accuracy=0.99),),
                    accuracy=0.99,
                ),
            ),
            rank_inputs=(
                UserStatsRankInput(
                    user_id=_USER_ID,
                    best_performances=(UserPerformanceBest(pp=Decimal("250"), accuracy=0.99),),
                ),
            ),
        )


@final
class RecordingPacketQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[int, tuple[bytes, ...]]] = []

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        self.enqueued.append((user_id, data))

    async def dequeue_all(self, user_id: int) -> bytes:
        _ = user_id
        return b""

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        _ = (user_id, ttl)


@final
class RecordingActiveSessionsQuery:
    def __init__(self, sessions: tuple[OnlineSessionSnapshot, ...]) -> None:
        self.sessions = sessions
        self.inputs: list[ListActiveSessionsQueryInput] = []

    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult:
        self.inputs.append(input_data)
        return ListActiveSessionsQueryResult(sessions=self.sessions)


@final
class RecordingWarmupResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | str, BeatmapResolveOptions | None]] = []

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        self.calls.append(("beatmap_id", beatmap_id, options))
        return _pending_result()

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        self.calls.append(("checksum", checksum_md5, options))
        return _pending_result()


def _status_payload(
    *,
    beatmap_id: int,
    beatmap_md5: str = _CHECKSUM,
    status_text: str = "playing",
    play_mode: int = 0,
) -> bytes:
    return status_change_payload(
        StatusUpdate(
            status=2,
            status_text=status_text,
            beatmap_md5=beatmap_md5,
            mods=0,
            play_mode=play_mode,
            beatmap_id=beatmap_id,
        )
    )


def _pending_result() -> BeatmapResolveResult:
    return BeatmapResolveResult(
        beatmap=None,
        beatmapset=None,
        eligibility=None,
        metadata_status=BeatmapFetchState.PENDING_FETCH,
        file_status=BeatmapFileState.MISSING,
        source=None,
        verified=False,
        last_fetched_at=None,
        next_refresh_at=None,
        reason="pending",
    )


def _warmup_logs(logs: list[EventDict]) -> list[EventDict]:
    return [entry for entry in logs if entry.get("event") == "beatmap_file_warmup"]


async def test_status_change_positive_beatmap_id_takes_priority_over_checksum() -> None:
    warmup = RecordingWarmupUseCase()
    handlers = StatusChangeHandlers(beatmap_file_warmup=warmup)

    await handlers.handle_status_change(
        _status_payload(beatmap_id=1234, beatmap_md5=_CHECKSUM),
        user_id=_USER_ID,
    )

    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=_USER_ID,
            beatmap_id=1234,
            checksum_md5=None,
        )
    ]


async def test_status_change_stores_current_play_mode() -> None:
    warmup = RecordingWarmupUseCase()
    status_store = RecordingStableUserStatusStore()
    handlers = StatusChangeHandlers(
        beatmap_file_warmup=warmup,
        stable_user_status_store=status_store,
    )

    await handlers.handle_status_change(
        _status_payload(beatmap_id=1234, beatmap_md5=_CHECKSUM, play_mode=3),
        user_id=_USER_ID,
    )

    assert status_store.play_modes == [(_USER_ID, 3)]


async def test_status_change_returns_own_user_stats_for_current_play_mode() -> None:
    warmup = RecordingWarmupUseCase()
    status_store = RecordingStableUserStatusStore()
    stats_repository = RecordingUserStatsQueryRepository()
    stats_query = CurrentUserStatsQuery(repository=stats_repository)
    packet_queue = RecordingPacketQueue()
    handlers = StatusChangeHandlers(
        beatmap_file_warmup=warmup,
        stable_user_status_store=status_store,
        current_user_stats_query=stats_query,
        packet_queue=packet_queue,
    )

    await handlers.handle_status_change(
        _status_payload(beatmap_id=1234, beatmap_md5=_CHECKSUM, play_mode=3),
        user_id=_USER_ID,
    )

    assert status_store.play_modes == [(_USER_ID, 3)]
    assert stats_repository.inputs == [
        CurrentUserStatsQueryInput(
            user_ids=(_USER_ID,),
            ruleset=Ruleset.MANIA,
            playstyle=Playstyle.VANILLA,
        )
    ]
    expected_packet = user_stats(
        user_id=_USER_ID,
        status=2,
        status_text="playing",
        beatmap_md5=_CHECKSUM,
        mods=0,
        play_mode=3,
        beatmap_id=1234,
        ranked_score=900_000,
        accuracy=0.99,
        play_count=5,
        total_score=900_000,
        rank=1,
        pp=250,
    )
    assert packet_queue.enqueued == [
        (
            _USER_ID,
            (expected_packet,),
        ),
    ]


async def test_status_change_fans_out_user_stats_to_online_sessions() -> None:
    warmup = RecordingWarmupUseCase()
    status_store = RecordingStableUserStatusStore()
    stats_repository = RecordingUserStatsQueryRepository()
    stats_query = CurrentUserStatsQuery(repository=stats_repository)
    packet_queue = RecordingPacketQueue()
    active_sessions_query = RecordingActiveSessionsQuery(
        (
            OnlineSessionSnapshot(
                user_id=100,
                username="Other",
                privileges=0,
                country="JP",
                utc_offset=9,
            ),
            OnlineSessionSnapshot(
                user_id=_USER_ID,
                username="Self",
                privileges=0,
                country="JP",
                utc_offset=9,
            ),
        )
    )
    handlers = StatusChangeHandlers(
        beatmap_file_warmup=warmup,
        stable_user_status_store=status_store,
        current_user_stats_query=stats_query,
        packet_queue=packet_queue,
        active_sessions_query=active_sessions_query,
    )

    await handlers.handle_status_change(
        _status_payload(beatmap_id=1234, beatmap_md5=_CHECKSUM, play_mode=3),
        user_id=_USER_ID,
    )

    assert active_sessions_query.inputs == [ListActiveSessionsQueryInput()]
    assert [recipient_id for recipient_id, _ in packet_queue.enqueued] == [_USER_ID, 100]
    assert packet_queue.enqueued[0][1] == packet_queue.enqueued[1][1]


async def test_request_status_returns_own_user_stats_for_stored_play_mode() -> None:
    warmup = RecordingWarmupUseCase()
    status_store = RecordingStableUserStatusStore()
    await status_store.set_status(
        _USER_ID,
        StableUserStatus(
            status=2,
            status_text="playing",
            beatmap_md5=_CHECKSUM,
            mods=0,
            play_mode=Ruleset.MANIA.value,
            beatmap_id=1234,
        ),
    )
    stats_repository = RecordingUserStatsQueryRepository()
    stats_query = CurrentUserStatsQuery(repository=stats_repository)
    packet_queue = RecordingPacketQueue()
    handlers = StatusChangeHandlers(
        beatmap_file_warmup=warmup,
        stable_user_status_store=status_store,
        current_user_stats_query=stats_query,
        packet_queue=packet_queue,
    )

    await handlers.handle_request_status(b"", user_id=_USER_ID)

    assert stats_repository.inputs == [
        CurrentUserStatsQueryInput(
            user_ids=(_USER_ID,),
            ruleset=Ruleset.MANIA,
            playstyle=Playstyle.VANILLA,
        )
    ]
    assert warmup.requests == []
    assert packet_queue.enqueued == [
        (
            _USER_ID,
            (
                user_stats(
                    user_id=_USER_ID,
                    status=2,
                    status_text="playing",
                    beatmap_md5=_CHECKSUM,
                    mods=0,
                    play_mode=3,
                    beatmap_id=1234,
                    ranked_score=900_000,
                    accuracy=0.99,
                    play_count=5,
                    total_score=900_000,
                    rank=1,
                    pp=250,
                ),
            ),
        )
    ]


async def test_status_change_checksum_fallback_uses_32_hex_when_id_is_not_positive() -> None:
    warmup = RecordingWarmupUseCase()
    handlers = StatusChangeHandlers(beatmap_file_warmup=warmup)

    await handlers.handle_status_change(
        _status_payload(beatmap_id=0, beatmap_md5=_CHECKSUM.upper()),
        user_id=_USER_ID,
    )

    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=_USER_ID,
            beatmap_id=None,
            checksum_md5=_CHECKSUM.upper(),
        )
    ]


async def test_status_change_without_beatmap_identity_logs_skip_without_fetch() -> None:
    resolver = RecordingWarmupResolver()
    handlers = StatusChangeHandlers(beatmap_file_warmup=RequestBeatmapFileWarmupUseCase(resolver))

    with structlog.testing.capture_logs() as logs:
        await handlers.handle_status_change(
            _status_payload(beatmap_id=0, beatmap_md5="not-a-32-hex-checksum"),
            user_id=_USER_ID,
        )

    assert resolver.calls == []
    events = _warmup_logs(logs)
    assert len(events) == 1
    assert events[0]["entrance"] == "stable_status_change"
    assert events[0]["outcome"] == "skipped_no_identity"
    assert events[0]["reason"] == "no_beatmap_identity"


async def test_status_change_decode_failure_is_logged_without_warmup_call() -> None:
    warmup = RecordingWarmupUseCase()
    handlers = StatusChangeHandlers(beatmap_file_warmup=warmup)

    with structlog.testing.capture_logs() as logs:
        await handlers.handle_status_change(b"\x02\x0b", user_id=_USER_ID)

    assert warmup.requests == []
    events = [
        entry for entry in logs if entry.get("event") == "status_change_warmup_decode_failed"
    ]
    assert len(events) == 1
    assert events[0]["user_id"] == _USER_ID
    assert events[0]["payload_size"] == 2
    assert "payload" not in events[0]
    assert "raw_payload" not in events[0]


async def test_status_change_warmup_failure_is_logged_without_raising() -> None:
    warmup = RecordingWarmupUseCase()
    warmup.raise_on_execute = RuntimeError("downstream failure with token=secret")
    handlers = StatusChangeHandlers(beatmap_file_warmup=warmup)

    with structlog.testing.capture_logs() as logs:
        await handlers.handle_status_change(_status_payload(beatmap_id=987), user_id=_USER_ID)

    assert len(warmup.requests) == 1
    events = [entry for entry in logs if entry.get("event") == "status_change_warmup_failed"]
    assert len(events) == 1
    assert events[0]["user_id"] == _USER_ID
    assert events[0]["exception_type"] == "RuntimeError"
    assert "token" not in events[0]
    assert "payload" not in events[0]
    assert "raw_payload" not in events[0]


async def test_status_change_repeated_reference_uses_consistent_warmup_identity() -> None:
    warmup = RecordingWarmupUseCase()
    handlers = StatusChangeHandlers(beatmap_file_warmup=warmup)
    payload = _status_payload(beatmap_id=555, beatmap_md5=_CHECKSUM)

    await handlers.handle_status_change(payload, user_id=_USER_ID)
    await handlers.handle_status_change(payload, user_id=_USER_ID)

    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=_USER_ID,
            beatmap_id=555,
            checksum_md5=None,
        ),
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=_USER_ID,
            beatmap_id=555,
            checksum_md5=None,
        ),
    ]


def test_status_change_handler_registers_status_change_packet() -> None:
    dispatcher = PacketDispatcher()
    handlers = StatusChangeHandlers(beatmap_file_warmup=RecordingWarmupUseCase())

    handlers.register_all(dispatcher)

    assert ClientPacketID.STATUS_CHANGE in dispatcher.get_handlers()
    assert ClientPacketID.REQUEST_STATUS in dispatcher.get_handlers()
