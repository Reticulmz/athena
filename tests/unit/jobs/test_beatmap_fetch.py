"""Tests for FetchBeatmapMetadataJob -- idempotent background metadata fetch.

TDD: RED phase first, then GREEN.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from osu_server.domain.beatmap import (
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
)
from osu_server.jobs.beatmap_fetch import FetchBeatmapMetadataJob
from osu_server.repositories.interfaces.beatmap_repository import (
    BeatmapFetchTarget,
)
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository
from osu_server.services.beatmaps.metadata_providers import (
    CompositeBeatmapMetadataProvider,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmap import BeatmapMetadataProvider

_NOW = datetime(2026, 6, 5, tzinfo=UTC)
_THIRTY_DAYS = timedelta(days=30)
_DEFAULT_CHECKSUM = "0123456789abcdef0123456789abcdef"
_ALT_CHECKSUM = "abcdef0123456789abcdef0123456789"


# ---------------------------------------------------------------------------
# Test doubles -- StubMetadataProvider conforms to BeatmapMetadataProvider
# ---------------------------------------------------------------------------


@dataclass
class StubMetadataProvider:
    """Simple in-memory provider that conforms to ``BeatmapMetadataProvider``.

    Returns ``BeatmapsetSnapshot | None`` for each lookup kind.
    """

    by_beatmap_id: dict[int, BeatmapsetSnapshot | None] = field(default_factory=dict)
    by_beatmapset_id: dict[int, BeatmapsetSnapshot | None] = field(default_factory=dict)
    by_checksum: dict[str, BeatmapsetSnapshot | None] = field(default_factory=dict)
    exception: Exception | None = None
    delay: float = 0
    calls: list[str] = field(default_factory=list)

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        self.calls.append(f"beatmap_id:{beatmap_id}")
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.exception is not None:
            raise self.exception
        return self.by_beatmap_id.get(beatmap_id)

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        self.calls.append(f"beatmapset_id:{beatmapset_id}")
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.exception is not None:
            raise self.exception
        return self.by_beatmapset_id.get(beatmapset_id)

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        self.calls.append(f"checksum:{checksum_md5}")
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.exception is not None:
            raise self.exception
        return self.by_checksum.get(checksum_md5)


# ---------------------------------------------------------------------------
# Snapshot factory helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    *,
    beatmap_id: int = 2000,
    beatmapset_id: int = 1000,
    checksum_md5: str = _DEFAULT_CHECKSUM,
    mode: str = "osu",
    version: str = "Another",
    artist: str = "Camellia",
    title: str = "Exit This Earth's Atomosphere",
    creator: str = "Realazy",
    source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    verified: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    official_status_source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    official_status_verified: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    beatmap_count: int = 1,
    last_fetched_at: datetime | None = None,
    next_refresh_at: datetime | None = None,
) -> BeatmapsetSnapshot:
    fetched_at = last_fetched_at or _NOW
    refresh_at = next_refresh_at or _NOW + _THIRTY_DAYS
    child_snapshots = [
        BeatmapSnapshot(
            beatmap_id=beatmap_id + i,
            beatmapset_id=beatmapset_id,
            checksum_md5=checksum_md5 if i == 0 else _ALT_CHECKSUM,
            mode=mode,
            version=version,
            official_status=official_status,
            official_status_source=official_status_source,
            official_status_verified=official_status_verified,
            last_fetched_at=fetched_at,
            next_refresh_at=refresh_at,
        )
        for i in range(beatmap_count)
    ]
    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist=artist,
        title=title,
        creator=creator,
        source=source,
        verified=verified,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        beatmaps=tuple(child_snapshots),
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


# ---------------------------------------------------------------------------
# FetchBeatmapMetadataJob tests
# ---------------------------------------------------------------------------


class TestFetchBeatmapMetadataJob:
    """Idempotent metadata fetch job behaviour."""

    @staticmethod
    def _make_job(
        repo: InMemoryBeatmapRepository,
        official: StubMetadataProvider | None = None,
        mirror: StubMetadataProvider | None = None,
    ) -> FetchBeatmapMetadataJob:
        _official: BeatmapMetadataProvider = official or StubMetadataProvider()
        _mirror: BeatmapMetadataProvider = mirror or StubMetadataProvider()
        composite = CompositeBeatmapMetadataProvider(official=_official, mirror=_mirror)
        return FetchBeatmapMetadataJob(repository=repo, metadata_provider=composite)

    # --- success path --------------------------------------------------------

    async def test_successful_official_fetch_saves_snapshot(self) -> None:
        """Official provider returns a snapshot; it is saved and fetch is marked
        succeeded."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved = await repo.get_beatmapset(snapshot.beatmapset_id)
        assert saved is not None
        assert saved.title == "Exit This Earth's Atomosphere"
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    # --- mirror fallback -----------------------------------------------------

    async def test_mirror_fallback_when_official_returns_none(self) -> None:
        """When the official provider returns None, fall back to mirror."""
        repo = InMemoryBeatmapRepository()
        mirror_snapshot = _make_mirror_snapshot()
        official = StubMetadataProvider()
        mirror = StubMetadataProvider(by_beatmap_id={2000: mirror_snapshot})
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved = await repo.get_beatmapset(mirror_snapshot.beatmapset_id)
        assert saved is not None
        assert saved.title == "Exit This Earth's Atomosphere"
        # Mirror was called (fallback)
        assert len(mirror.calls) == 1

    async def test_mirror_fallback_when_official_raises(self) -> None:
        """When the official provider raises, fall back to mirror."""
        repo = InMemoryBeatmapRepository()
        mirror_snapshot = _make_mirror_snapshot()
        official = StubMetadataProvider(exception=RuntimeError("official down"))
        mirror = StubMetadataProvider(by_beatmap_id={2000: mirror_snapshot})
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved = await repo.get_beatmapset(mirror_snapshot.beatmapset_id)
        assert saved is not None

    # --- failure path --------------------------------------------------------

    async def test_mark_failed_when_all_providers_return_none(self) -> None:
        """When both providers return None, the fetch is marked failed."""
        repo = InMemoryBeatmapRepository()
        official = StubMetadataProvider()
        mirror = StubMetadataProvider()
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED
        assert fetch_record.last_error is not None

    async def test_mark_failed_when_all_providers_raise(self) -> None:
        """When both providers raise, the fetch is marked failed."""
        repo = InMemoryBeatmapRepository()
        official = StubMetadataProvider(exception=RuntimeError("official down"))
        mirror = StubMetadataProvider(exception=RuntimeError("mirror down"))
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED

    # --- idempotency ---------------------------------------------------------

    async def test_already_pending_skips_fetch(self) -> None:
        """When the target is already in PENDING_FETCH state, the job returns
        without contacting any provider."""
        repo = InMemoryBeatmapRepository()
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)
        # Pre-mark as pending so the job sees it is already claimed.
        _ = await repo.try_mark_fetch_pending(target, _NOW)

        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)

        await job.execute(target)

        # The provider was never called because the pending gate returned False.
        assert len(official.calls) == 0

    async def test_concurrent_calls_only_one_proceeds(self) -> None:
        """Two concurrent calls for the same target: the second should see
        the pending state and exit without fetching."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(
            by_beatmap_id={2000: snapshot},
            delay=0.05,  # Give the second call time to observe pending state
        )
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        _ = await asyncio.gather(
            job.execute(target),
            job.execute(target),
        )

        # The provider should have been called only once (by the first task).
        assert len(official.calls) == 1
        # State should be fresh (from the successful first call).
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    # --- local override preservation -----------------------------------------

    async def test_official_refresh_preserves_local_status_override(self) -> None:
        """When a beatmap already has a local_status_override, re-fetching
        official metadata does not clear it."""
        from osu_server.domain.beatmap import LocalBeatmapStatus  # noqa: PLC0415

        repo = InMemoryBeatmapRepository()
        # Save initial snapshot with local override set on the beatmap.
        initial_snapshot = _make_snapshot()
        initial_beatset = _snapshot_to_beatmapset(initial_snapshot)
        await repo.save_beatmapset_snapshot(initial_beatset)
        _ = await repo.set_local_status_override(2000, LocalBeatmapStatus.LOVED)

        # Now re-fetch the same beatmap via the job.
        official = StubMetadataProvider(by_beatmap_id={2000: _make_snapshot()})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved_beatmap = await repo.get_beatmap(2000)
        assert saved_beatmap is not None
        assert saved_beatmap.local_status_override is LocalBeatmapStatus.LOVED

    # --- mirror snapshot verification state ----------------------------------

    async def test_mirror_snapshot_saved_as_unverified(self) -> None:
        """Mirror-sourced snapshots are saved with unverified status per-beatmap."""
        repo = InMemoryBeatmapRepository()
        mirror_snapshot = _make_mirror_snapshot()
        mirror = StubMetadataProvider(by_beatmap_id={2000: mirror_snapshot})
        job = self._make_job(repo, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved_beatmap = await repo.get_beatmap(2000)
        assert saved_beatmap is not None
        assert saved_beatmap.official_status_verified is BeatmapSourceVerification.UNVERIFIED

    # --- source tracking (req 16.1) ------------------------------------------

    async def test_official_source_tracked_in_saved_snapshot(self) -> None:
        """Official fetch records the source in the saved beatmap metadata."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot(
            official_status_source=BeatmapMetadataSource.OFFICIAL,
        )
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved_beatmap = await repo.get_beatmap(2000)
        assert saved_beatmap is not None
        assert saved_beatmap.official_status_source is BeatmapMetadataSource.OFFICIAL

    # --- fetch state after re-fetch -----------------------------------------

    async def test_re_fetch_after_fresh_state_marks_succeeded(self) -> None:
        """After a successful fetch, a subsequent fetch still proceeds
        (state is FRESH, not PENDING_FETCH) and succeeds normally."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        # First fetch
        await job.execute(target)
        # Second fetch
        await job.execute(target)

        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    # --- lookup by beatmapset_id ---------------------------------------------

    async def test_lookup_by_beatmapset_id(self) -> None:
        """The job resolves metadata:beatmapset targets via the provider's
        beatmapset_id lookup."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot(beatmapset_id=5678)
        official = StubMetadataProvider(by_beatmapset_id={5678: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmapset_id(5678)

        await job.execute(target)

        saved = await repo.get_beatmapset(5678)
        assert saved is not None
        assert saved.id == 5678

    # --- lookup by checksum --------------------------------------------------

    async def test_lookup_by_checksum(self) -> None:
        """The job resolves metadata:checksum targets via the provider's
        checksum lookup."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot()
        checksum = _DEFAULT_CHECKSUM
        official = StubMetadataProvider(by_checksum={checksum: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_checksum(checksum)

        await job.execute(target)

        saved_beatmap = await repo.get_beatmap(2000)
        assert saved_beatmap is not None


# ---------------------------------------------------------------------------
# Conversion helper (used by tests that pre-populate repo state)
# ---------------------------------------------------------------------------


def _snapshot_to_beatmapset(snapshot: BeatmapsetSnapshot) -> BeatmapSet:
    """Convert a domain snapshot to a domain BeatmapSet for test setup."""
    from osu_server.domain.beatmap import Beatmap  # noqa: PLC0415

    beatmaps = [
        Beatmap(
            id=bm.beatmap_id,
            beatmapset_id=bm.beatmapset_id,
            checksum_md5=bm.checksum_md5,
            mode=bm.mode,
            version=bm.version,
            total_length=bm.total_length,
            hit_length=bm.hit_length,
            max_combo=bm.max_combo,
            bpm=bm.bpm,
            cs=bm.cs,
            od=bm.od,
            ar=bm.ar,
            hp=bm.hp,
            difficulty_rating=bm.difficulty_rating,
            official_status=bm.official_status,
            official_status_source=bm.official_status_source,
            official_status_verified=bm.official_status_verified,
            local_status_override=bm.local_status_override,
            metadata_fetch_state=BeatmapFetchState.FRESH,
            file_state=BeatmapFileState.MISSING,
            file_attachment=None,
            last_fetched_at=bm.last_fetched_at,
            next_refresh_at=bm.next_refresh_at,
        )
        for bm in snapshot.beatmaps
    ]
    return BeatmapSet(
        id=snapshot.beatmapset_id,
        artist=snapshot.artist,
        title=snapshot.title,
        creator=snapshot.creator,
        artist_unicode=snapshot.artist_unicode,
        title_unicode=snapshot.title_unicode,
        official_status=snapshot.official_status,
        official_status_source=snapshot.official_status_source,
        official_status_verified=snapshot.official_status_verified,
        beatmaps=tuple(beatmaps),
        last_fetched_at=snapshot.last_fetched_at,
        next_refresh_at=snapshot.next_refresh_at,
    )
