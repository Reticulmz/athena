"""Beatmap file warmup request identity policy tests."""

from __future__ import annotations

from typing import final

from structlog.testing import capture_logs

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapResolveOptions,
    BeatmapResolveResult,
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
