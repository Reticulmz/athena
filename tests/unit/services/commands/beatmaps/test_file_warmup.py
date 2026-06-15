"""Beatmap file warmup request identity policy tests."""

from __future__ import annotations

from dataclasses import replace
from typing import final

from structlog.testing import capture_logs

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSourceVerification,
)
from osu_server.services.commands.beatmaps.file_warmup import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupOutcome,
    BeatmapFileWarmupRequest,
    RequestBeatmapFileWarmupUseCase,
)


@final
class RecordingWarmupResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | str, BeatmapResolveOptions | None]] = []
        self.result = _pending_result()

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        self.calls.append(("beatmap_id", beatmap_id, options))
        return self.result

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        self.calls.append(("checksum", checksum_md5, options))
        return self.result


@final
class FailingWarmupResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | str, BeatmapResolveOptions | None]] = []

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        self.calls.append(("beatmap_id", beatmap_id, options))
        raise RuntimeError("credential=secret replay bytes should not be logged")

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        self.calls.append(("checksum", checksum_md5, options))
        raise RuntimeError("raw payload should not be logged")


async def test_no_beatmap_identity_skips_without_resolver_call() -> None:
    resolver = RecordingWarmupResolver()
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    with capture_logs() as logs:
        result = await use_case.execute(
            BeatmapFileWarmupRequest(
                entrance=BeatmapFileWarmupEntrance.STABLE_GETSCORES,
                user_id=2,
            )
        )

    assert result.outcome is BeatmapFileWarmupOutcome.SKIPPED_NO_IDENTITY
    assert result.entrance is BeatmapFileWarmupEntrance.STABLE_GETSCORES
    assert result.user_id == 2
    assert result.beatmap_id is None
    assert result.checksum_md5 is None
    assert result.reason == "no_beatmap_identity"
    assert resolver.calls == []

    events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert len(events) == 1
    assert events[0]["outcome"] == "skipped_no_identity"
    assert events[0]["reason"] == "no_beatmap_identity"
    assert events[0]["entrance"] == "stable_getscores"


async def test_malformed_beatmap_identity_skips_without_resolver_call() -> None:
    resolver = RecordingWarmupResolver()
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    with capture_logs() as logs:
        result = await use_case.execute(
            BeatmapFileWarmupRequest(
                entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
                user_id=3,
                beatmap_id=-1,
                checksum_md5="not-an-md5",
            )
        )

    assert result.outcome is BeatmapFileWarmupOutcome.SKIPPED_MALFORMED_IDENTITY
    assert result.entrance is BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE
    assert result.user_id == 3
    assert result.beatmap_id is None
    assert result.checksum_md5 is None
    assert result.reason == "malformed_beatmap_identity"
    assert resolver.calls == []

    events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert len(events) == 1
    assert events[0]["outcome"] == "skipped_malformed_identity"
    assert events[0]["reason"] == "malformed_beatmap_identity"
    assert events[0]["entrance"] == "stable_status_change"


async def test_positive_beatmap_id_takes_priority_over_checksum() -> None:
    resolver = RecordingWarmupResolver()
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    _ = await use_case.execute(
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_SCORE_SUBMIT_FALLBACK,
            user_id=4,
            beatmap_id=75,
            checksum_md5="3B0AECD99EBA50FFC7BFF8DA117D0E06",
        )
    )

    assert len(resolver.calls) == 1
    method, value, options = resolver.calls[0]
    assert method == "beatmap_id"
    assert value == 75
    assert options is not None
    assert options.require_osu_file is True
    assert options.wait_timeout_seconds == 0.0


async def test_checksum_identity_is_normalized_before_resolver_call() -> None:
    resolver = RecordingWarmupResolver()
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    _ = await use_case.execute(
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=5,
            checksum_md5="3B0AECD99EBA50FFC7BFF8DA117D0E06",
        )
    )

    assert len(resolver.calls) == 1
    method, value, options = resolver.calls[0]
    assert method == "checksum"
    assert value == "3b0aecd99eba50ffc7bff8da117d0e06"
    assert options is not None
    assert options.require_osu_file is True
    assert options.wait_timeout_seconds == 0.0


async def test_available_file_maps_to_already_available_noop() -> None:
    resolver = RecordingWarmupResolver()
    resolver.result = _known_result(beatmap_id=42, file_status=BeatmapFileState.AVAILABLE)
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    with capture_logs() as logs:
        result = await use_case.execute(
            BeatmapFileWarmupRequest(
                entrance=BeatmapFileWarmupEntrance.STABLE_GETSCORES,
                user_id=6,
                beatmap_id=42,
            )
        )

    assert result.outcome is BeatmapFileWarmupOutcome.ALREADY_AVAILABLE
    assert result.beatmap_id == 42
    assert result.checksum_md5 is None
    assert result.reason == "file_available"
    assert len(resolver.calls) == 1

    events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert len(events) == 1
    assert events[0]["outcome"] == "already_available"
    assert events[0]["reason"] == "file_available"


async def test_available_file_uses_noop_reason_when_metadata_is_stale() -> None:
    resolver = RecordingWarmupResolver()
    resolver.result = replace(
        _known_result(beatmap_id=42, file_status=BeatmapFileState.AVAILABLE),
        reason="stale",
    )
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    with capture_logs() as logs:
        result = await use_case.execute(
            BeatmapFileWarmupRequest(
                entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
                user_id=6,
                beatmap_id=42,
            )
        )

    assert result.outcome is BeatmapFileWarmupOutcome.ALREADY_AVAILABLE
    assert result.reason == "file_available"
    events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert len(events) == 1
    assert events[0]["outcome"] == "already_available"
    assert events[0]["reason"] == "file_available"


async def test_known_beatmap_missing_file_maps_to_requested() -> None:
    resolver = RecordingWarmupResolver()
    resolver.result = _known_result(beatmap_id=43, file_status=BeatmapFileState.MISSING)
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    result = await use_case.execute(
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=7,
            beatmap_id=43,
        )
    )

    assert result.outcome is BeatmapFileWarmupOutcome.REQUESTED
    assert result.beatmap_id == 43
    assert result.reason == "file_missing"


async def test_checksum_only_unresolved_beatmap_maps_to_metadata_pending() -> None:
    resolver = RecordingWarmupResolver()
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    result = await use_case.execute(
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=8,
            checksum_md5="3b0aecd99eba50ffc7bff8da117d0e06",
        )
    )

    assert result.outcome is BeatmapFileWarmupOutcome.METADATA_PENDING
    assert result.beatmap_id is None
    assert result.checksum_md5 == "3b0aecd99eba50ffc7bff8da117d0e06"
    assert result.reason == "pending"


async def test_resolver_failure_returns_failed_and_logs_sanitized_diagnostics() -> None:
    resolver = FailingWarmupResolver()
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    with capture_logs() as logs:
        result = await use_case.execute(
            BeatmapFileWarmupRequest(
                entrance=BeatmapFileWarmupEntrance.STABLE_SCORE_SUBMIT_FALLBACK,
                user_id=9,
                beatmap_id=44,
            )
        )

    assert result.outcome is BeatmapFileWarmupOutcome.FAILED
    assert result.beatmap_id == 44
    assert result.checksum_md5 is None
    assert result.reason == "resolver_failure"

    events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert len(events) == 1
    event = events[0]
    assert event["outcome"] == "failed"
    assert event["reason"] == "resolver_failure"
    assert event["exception_type"] == "RuntimeError"
    assert "credential" not in event
    assert "raw_payload" not in event
    assert "replay_bytes" not in event


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


def _known_result(
    *,
    beatmap_id: int,
    file_status: BeatmapFileState,
) -> BeatmapResolveResult:
    beatmap = Beatmap(
        id=beatmap_id,
        beatmapset_id=24,
        checksum_md5="3b0aecd99eba50ffc7bff8da117d0e06",
        mode="osu",
        version="Insane",
        total_length=None,
        hit_length=None,
        max_combo=None,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=file_status,
        file_attachment=None,
        last_fetched_at=None,
        next_refresh_at=None,
    )
    return BeatmapResolveResult(
        beatmap=beatmap,
        beatmapset=None,
        eligibility=None,
        metadata_status=BeatmapFetchState.FRESH,
        file_status=file_status,
        source=BeatmapMetadataSource.MIRROR,
        verified=False,
        last_fetched_at=None,
        next_refresh_at=None,
        reason="file_available" if file_status is BeatmapFileState.AVAILABLE else "file_missing",
    )
