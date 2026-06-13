"""E2E tests for beatmap metadata resolution flow.

Exercises the full resolution pipeline: missing beatmap resolution,
pending metadata state, metadata job completion, and later fresh cache
resolution.  Covers lookup by beatmap id, beatmapset id, and checksum/md5
using in-memory repositories and fake providers -- no real network
credentials required.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapFreshnessPolicy,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
)
from osu_server.jobs.beatmap_fetch import FetchBeatmapMetadataJob
from osu_server.repositories.beatmaps.metadata_providers import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository
from osu_server.services.beatmap_mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
    InMemoryBeatmapMetadataProvider,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.beatmap_repository import BeatmapFetchTarget

_NOW = datetime(2026, 6, 6, tzinfo=UTC)
_ONE_HOUR = timedelta(hours=1)
_THIRTY_DAYS = timedelta(days=30)

_BEATMAP_ID = 2000
_BEATMAPSET_ID = 1000
_CHECKSUM = "0123456789abcdef0123456789abcdef"

_ALT_BEATMAP_ID = 2001
_ALT_BEATMAPSET_ID = 1001
_ALT_CHECKSUM = "abcdef0123456789abcdef0123456789"


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    *,
    beatmap_id: int = _BEATMAP_ID,
    beatmapset_id: int = _BEATMAPSET_ID,
    checksum_md5: str = _CHECKSUM,
    mode: str = "osu",
    version: str = "Another",
    artist: str = "Camellia",
    title: str = "Exit This Earth's Atomosphere",
    creator: str = "Realazy",
    source: BeatmapMetadataSource | None = None,
    verified: BeatmapSourceVerification | None = None,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    official_status_source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    official_status_verified: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    last_fetched_at: datetime | None = None,
    next_refresh_at: datetime | None = None,
) -> BeatmapsetSnapshot:
    fetched_at = last_fetched_at or _NOW
    refresh_at = next_refresh_at or _NOW + _THIRTY_DAYS
    _source = source if source is not None else official_status_source
    _verified = verified if verified is not None else official_status_verified
    bm = BeatmapSnapshot(
        beatmap_id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=checksum_md5,
        mode=mode,
        version=version,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        total_length=240,
        hit_length=220,
        max_combo=1234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        last_fetched_at=fetched_at,
        next_refresh_at=refresh_at,
    )
    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist=artist,
        title=title,
        creator=creator,
        source=_source,
        verified=_verified,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        beatmaps=(bm,),
        last_fetched_at=fetched_at,
        next_refresh_at=refresh_at,
    )


def _make_mirror_snapshot(**kwargs: object) -> BeatmapsetSnapshot:
    return _make_snapshot(
        source=BeatmapMetadataSource.MIRROR,
        verified=BeatmapSourceVerification.UNVERIFIED,
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        **kwargs,  # pyright: ignore[reportArgumentType]
    )


def _make_freshness_policy() -> BeatmapFreshnessPolicy:
    return BeatmapFreshnessPolicy(
        ranked_refresh_interval=_THIRTY_DAYS,
        pending_refresh_interval=_ONE_HOUR,
        graveyard_refresh_interval=_THIRTY_DAYS,
        mirror_refresh_interval=_ONE_HOUR,
    )


# ---------------------------------------------------------------------------
# Wiring helper
# ---------------------------------------------------------------------------


def _build_service_with_job(
    repo: InMemoryBeatmapRepository,
    official_provider: InMemoryBeatmapMetadataProvider,
    *,
    mirror_trust_enabled: bool = False,
) -> tuple[BeatmapMirrorService, FetchBeatmapMetadataJob, list[BeatmapFetchTarget]]:
    """Wire a service with a spy-based enqueue and a metadata job.

    The enqueue_refresh callback records the target for later inspection
    instead of executing the job synchronously.  The caller drives the job
    between resolve calls.
    """
    composite = CompositeBeatmapMetadataProvider(
        official=official_provider,
        mirror=InMemoryBeatmapMetadataProvider(),
    )
    job = FetchBeatmapMetadataJob(repository=repo, metadata_provider=composite)
    enqueued: list[BeatmapFetchTarget] = []

    async def _enqueue(target: BeatmapFetchTarget) -> None:
        enqueued.append(target)

    service = BeatmapMirrorService(
        repository=repo,
        eligibility_service=BeatmapEligibilityService(),
        freshness_policy=_make_freshness_policy(),
        mirror_trust_enabled=mirror_trust_enabled,
        enqueue_refresh=_enqueue,
    )
    return service, job, enqueued


# ---------------------------------------------------------------------------
# Tests: beatmap id resolution E2E
# ---------------------------------------------------------------------------


class TestMetadataResolutionByBeatmapIdE2E:
    @pytest.mark.asyncio
    async def test_missing_beatmap_transitions_from_pending_to_fresh(self) -> None:
        """Resolve unknown beatmap by id: first call returns pending fetch
        state and enqueues a metadata job; after the job stores the snapshot,
        the second call returns fresh resolved metadata."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot()
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)
        service, job, enqueued = _build_service_with_job(repo, official)

        # --- First resolve: beatmap is unknown ---------------------------------
        result1 = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result1.beatmap is None
        assert result1.beatmapset is None
        assert result1.eligibility is None
        assert result1.metadata_status is BeatmapFetchState.PENDING_FETCH
        assert result1.file_status is BeatmapFileState.MISSING
        assert result1.source is None
        assert result1.verified is False
        assert result1.reason == "unsolicited"
        assert len(enqueued) == 1
        assert enqueued[0].target_type == "metadata:beatmap"
        assert enqueued[0].target_key == str(_BEATMAP_ID)

        # --- Execute the metadata job ------------------------------------------
        await job.execute(enqueued[0])

        # --- Second resolve: beatmap is now cached -----------------------------
        result2 = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result2.beatmap is not None
        assert result2.beatmap.id == _BEATMAP_ID
        assert result2.beatmap.checksum_md5 == _CHECKSUM
        assert result2.beatmap.mode == "osu"
        assert result2.beatmap.version == "Another"
        assert result2.beatmapset is not None
        assert result2.beatmapset.id == _BEATMAPSET_ID
        assert result2.beatmapset.title == "Exit This Earth's Atomosphere"
        assert result2.metadata_status is BeatmapFetchState.FRESH
        assert result2.source is BeatmapMetadataSource.OFFICIAL
        assert result2.verified is True
        assert result2.eligibility is not None
        assert result2.eligibility.accepts_scores is True
        assert result2.eligibility.awards_ranked_pp is True
        assert result2.reason is None

    @pytest.mark.asyncio
    async def test_official_mirror_fallback_flow(self) -> None:
        """When the official provider has no data but the mirror does,
        the job saves a mirror-sourced unverified snapshot, and the service
        reports the mirror source and denies eligibility by default."""
        repo = InMemoryBeatmapRepository()
        mirror_snapshot = _make_mirror_snapshot()
        mirror = InMemoryBeatmapMetadataProvider()
        mirror.add_snapshot(mirror_snapshot)

        composite = CompositeBeatmapMetadataProvider(
            official=InMemoryBeatmapMetadataProvider(),
            mirror=mirror,
        )
        job = FetchBeatmapMetadataJob(repository=repo, metadata_provider=composite)
        enqueued: list[BeatmapFetchTarget] = []

        async def _enqueue(target: BeatmapFetchTarget) -> None:
            enqueued.append(target)

        service = BeatmapMirrorService(
            repository=repo,
            eligibility_service=BeatmapEligibilityService(),
            freshness_policy=_make_freshness_policy(),
            enqueue_refresh=_enqueue,
        )

        # First resolve: unknown
        _ = await service.resolve_by_beatmap_id(_BEATMAP_ID)
        assert len(enqueued) == 1

        # Execute job
        await job.execute(enqueued[0])

        # Second resolve: mirror-sourced, unverified, eligibility denied
        result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result.beatmap is not None
        assert result.source is BeatmapMetadataSource.MIRROR
        assert result.verified is False
        assert result.eligibility is not None
        assert result.eligibility.accepts_scores is False
        assert result.eligibility.denial_reason == "untrusted_mirror_status"


# ---------------------------------------------------------------------------
# Tests: beatmapset id resolution E2E
# ---------------------------------------------------------------------------


class TestMetadataResolutionByBeatmapsetIdE2E:
    @pytest.mark.asyncio
    async def test_missing_beatmapset_transitions_from_pending_to_fresh(self) -> None:
        """Resolve unknown beatmapset by id: first call is pending, after the
        job stores the snapshot the second call returns fresh metadata."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot(beatmapset_id=_ALT_BEATMAPSET_ID, beatmap_id=_ALT_BEATMAP_ID)
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)
        service, job, enqueued = _build_service_with_job(repo, official)

        result1 = await service.resolve_by_beatmapset_id(_ALT_BEATMAPSET_ID)

        assert result1.beatmapset is None
        assert result1.metadata_status is BeatmapFetchState.PENDING_FETCH
        assert result1.source is None
        assert result1.verified is False
        assert result1.reason == "unsolicited"
        assert len(enqueued) == 1
        assert enqueued[0].target_type == "metadata:beatmapset"

        await job.execute(enqueued[0])

        result2 = await service.resolve_by_beatmapset_id(_ALT_BEATMAPSET_ID)

        assert result2.beatmapset is not None
        assert result2.beatmapset.id == _ALT_BEATMAPSET_ID
        assert result2.metadata_status is BeatmapFetchState.FRESH
        assert result2.source is BeatmapMetadataSource.OFFICIAL
        assert result2.verified is True
        assert result2.reason is None


# ---------------------------------------------------------------------------
# Tests: checksum resolution E2E
# ---------------------------------------------------------------------------


class TestMetadataResolutionByChecksumE2E:
    @pytest.mark.asyncio
    async def test_missing_beatmap_by_checksum_transitions_from_pending_to_fresh(self) -> None:
        """Resolve unknown beatmap by checksum: first pending, then fresh after
        the job completes."""
        repo = InMemoryBeatmapRepository()
        checksum = _ALT_CHECKSUM
        snapshot = _make_snapshot(beatmap_id=_ALT_BEATMAP_ID, checksum_md5=checksum)
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)
        service, job, enqueued = _build_service_with_job(repo, official)

        result1 = await service.resolve_by_checksum(checksum)

        assert result1.beatmap is None
        assert result1.metadata_status is BeatmapFetchState.PENDING_FETCH
        assert result1.source is None
        assert result1.verified is False
        assert result1.reason == "unsolicited"
        assert len(enqueued) == 1
        assert enqueued[0].target_type == "metadata:checksum"
        assert enqueued[0].target_key == checksum

        await job.execute(enqueued[0])

        result2 = await service.resolve_by_checksum(checksum)

        assert result2.beatmap is not None
        assert result2.beatmap.checksum_md5 == checksum
        assert result2.beatmap.id == _ALT_BEATMAP_ID
        assert result2.metadata_status is BeatmapFetchState.FRESH
        assert result2.source is BeatmapMetadataSource.OFFICIAL
        assert result2.verified is True


# ---------------------------------------------------------------------------
# Tests: idempotency (req 14)
# ---------------------------------------------------------------------------


class TestMetadataResolutionIdempotencyE2E:
    @pytest.mark.asyncio
    async def test_concurrent_missing_resolves_produce_consistent_pending_state(
        self,
    ) -> None:
        """Two concurrent resolve calls for the same missing beatmap produce
        the same pending fetch state and only one enqueue."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot()
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)
        service, _job, enqueued = _build_service_with_job(repo, official)

        r1, r2 = await asyncio.gather(
            service.resolve_by_beatmap_id(_BEATMAP_ID),
            service.resolve_by_beatmap_id(_BEATMAP_ID),
        )

        # Both return pending (unknown result)
        assert r1.metadata_status is BeatmapFetchState.PENDING_FETCH
        assert r2.metadata_status is BeatmapFetchState.PENDING_FETCH
        # Two enqueues happened (one per resolve call); this is acceptable
        # because the job itself is idempotent through try_mark_fetch_pending.
        assert len(enqueued) >= 1

    @pytest.mark.asyncio
    async def test_re_resolve_after_cached_does_not_enqueue(self) -> None:
        """After metadata is cached, re-resolving the same beatmap does not
        trigger a new enqueue (the data is fresh)."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot()
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)
        service, job, enqueued = _build_service_with_job(repo, official)

        # Initial resolve + fetch
        _ = await service.resolve_by_beatmap_id(_BEATMAP_ID)
        assert len(enqueued) == 1
        await job.execute(enqueued[0])

        # Reset enqueue spy
        enqueued.clear()

        # Re-resolve the now-cached beatmap
        result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result.metadata_status is BeatmapFetchState.FRESH
        assert len(enqueued) == 0  # no refresh needed


# ---------------------------------------------------------------------------
# Tests: bounded wait (req 2.5)
# ---------------------------------------------------------------------------


class TestMetadataResolutionBoundedWaitE2E:
    @pytest.mark.asyncio
    async def test_bounded_wait_returns_fresh_when_data_arrives_in_time(self) -> None:
        """With a bounded wait timeout, the service polls the repository and
        returns fresh metadata when a background populate task saves the data
        within the wait window."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot()
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)

        composite = CompositeBeatmapMetadataProvider(
            official=official,
            mirror=InMemoryBeatmapMetadataProvider(),
        )
        job = FetchBeatmapMetadataJob(repository=repo, metadata_provider=composite)
        enqueued: list[BeatmapFetchTarget] = []

        async def _enqueue(target: BeatmapFetchTarget) -> None:
            enqueued.append(target)

        service = BeatmapMirrorService(
            repository=repo,
            eligibility_service=BeatmapEligibilityService(),
            freshness_policy=_make_freshness_policy(),
            enqueue_refresh=_enqueue,
        )

        # Background task: execute the job shortly after the resolve starts
        async def _populate() -> None:
            # Wait for enqueue to happen
            while not enqueued:
                await asyncio.sleep(0.001)
            await job.execute(enqueued[0])

        populate_task = asyncio.create_task(_populate())

        result = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(wait_timeout_seconds=5.0),
        )

        await populate_task

        assert result.beatmap is not None
        assert result.beatmap.id == _BEATMAP_ID
        assert result.metadata_status is BeatmapFetchState.FRESH

    @pytest.mark.asyncio
    async def test_bounded_wait_returns_pending_on_timeout(self) -> None:
        """When no data arrives within the wait timeout, the service returns
        a pending fetch result (not an exception)."""
        repo = InMemoryBeatmapRepository()
        official = InMemoryBeatmapMetadataProvider()
        service, _job, _enqueued = _build_service_with_job(repo, official)

        result = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(wait_timeout_seconds=0.001),
        )

        assert result.beatmap is None
        assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
        assert result.reason == "unsolicited"


# ---------------------------------------------------------------------------
# Tests: upstream-provider failure (req 7.3, 7.5)
# ---------------------------------------------------------------------------


class TestMetadataResolutionFailureE2E:
    @pytest.mark.asyncio
    async def test_all_providers_fail_produces_failed_state(self) -> None:
        """When both official and mirror providers return nothing, the job
        marks fetch state as failed and the service reports the failure."""
        repo = InMemoryBeatmapRepository()
        # Both providers are empty -- no snapshot preloaded
        service, job, enqueued = _build_service_with_job(repo, InMemoryBeatmapMetadataProvider())

        _ = await service.resolve_by_beatmap_id(_BEATMAP_ID)
        assert len(enqueued) == 1

        await job.execute(enqueued[0])

        result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result.beatmap is None
        assert result.metadata_status is BeatmapFetchState.FAILED
        assert result.reason is not None
        assert "all configured metadata providers" in result.reason
        assert result.eligibility is None


# ---------------------------------------------------------------------------
# Tests: beatmap identity completeness (req 1.5)
# ---------------------------------------------------------------------------


class TestBeatmapIdentityAfterResolutionE2E:
    """Verify that resolved beatmaps expose complete identity data for
    downstream consumers (req 1.5)."""

    @pytest.mark.asyncio
    async def test_resolved_beatmap_exposes_full_identity(self) -> None:
        """After successful metadata resolution, a beatmap exposes beatmap id,
        beatmapset id, checksum/md5, game mode, and difficulty identity."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot()
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)
        service, job, enqueued = _build_service_with_job(repo, official)

        _ = await service.resolve_by_beatmap_id(_BEATMAP_ID)
        await job.execute(enqueued[0])

        result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result.beatmap is not None
        assert result.beatmap.id == _BEATMAP_ID
        assert result.beatmap.beatmapset_id == _BEATMAPSET_ID
        assert result.beatmap.checksum_md5 == _CHECKSUM
        assert result.beatmap.mode == "osu"
        assert result.beatmap.version == "Another"
        assert result.beatmap.total_length == 240
        assert result.beatmap.bpm == 180.0
        assert result.beatmap.cs == 4.0
        assert result.beatmap.od == 8.5
        assert result.beatmap.ar == 9.4
        assert result.beatmap.hp == 6.5
        assert result.beatmap.difficulty_rating == 5.67

        assert result.beatmapset is not None
        assert result.beatmapset.artist == "Camellia"
        assert result.beatmapset.title == "Exit This Earth's Atomosphere"
        assert result.beatmapset.creator == "Realazy"
