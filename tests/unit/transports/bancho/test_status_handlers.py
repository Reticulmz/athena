"""Tests for STATUS_CHANGE beatmap file warmup handling."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

import structlog.testing
from caterpillar.model import pack

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapResolveOptions,
    BeatmapResolveResult,
)
from osu_server.services.commands.beatmaps import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupOutcome,
    BeatmapFileWarmupRequest,
    BeatmapFileWarmupResult,
    RequestBeatmapFileWarmupUseCase,
)
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.handlers.status import StatusChangeHandlers
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
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
) -> bytes:
    return pack(
        StatusUpdate(
            status=2,
            status_text=status_text,
            beatmap_md5=beatmap_md5,
            mods=0,
            play_mode=0,
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
