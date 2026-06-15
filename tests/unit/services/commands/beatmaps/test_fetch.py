"""Tests for beatmap fetch jobs.

Covers:
- ``FetchBeatmapMetadataUseCase`` idempotent background metadata fetch.
- ``FetchBeatmapFileUseCase`` idempotent .osu file fetch.
- taskiq job adapter registration and runtime-unavailable handling.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from tests.support.beatmaps import InMemoryBeatmapStore

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
    OsuFileFetchResult,
)
from osu_server.domain.storage.blobs import Blob
from osu_server.repositories.beatmaps.metadata_providers import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import Beatmap, BeatmapMetadataProvider
    from osu_server.domain.storage.blobs import BlobStored

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
# FetchBeatmapMetadataUseCase tests
# ---------------------------------------------------------------------------


class TestFetchBeatmapMetadataUseCase:
    """Idempotent metadata fetch job behaviour."""

    @staticmethod
    def _make_job(
        repo: InMemoryBeatmapStore,
        official: StubMetadataProvider | None = None,
        mirror: StubMetadataProvider | None = None,
    ) -> FetchBeatmapMetadataUseCase:
        _official: BeatmapMetadataProvider = official or StubMetadataProvider()
        _mirror: BeatmapMetadataProvider = mirror or StubMetadataProvider()
        composite = CompositeBeatmapMetadataProvider(official=_official, mirror=_mirror)
        return FetchBeatmapMetadataUseCase(
            uow_factory=repo.uow_factory,
            metadata_provider=composite,
        )

    # --- success path --------------------------------------------------------

    async def test_successful_official_fetch_saves_snapshot(self) -> None:
        """Official provider returns a snapshot; it is saved and fetch is marked
        succeeded."""
        repo = InMemoryBeatmapStore()
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
        repo = InMemoryBeatmapStore()
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
        repo = InMemoryBeatmapStore()
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
        repo = InMemoryBeatmapStore()
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
        repo = InMemoryBeatmapStore()
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
        repo = InMemoryBeatmapStore()
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
        repo = InMemoryBeatmapStore()
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
        from osu_server.domain.beatmaps import LocalBeatmapStatus  # noqa: PLC0415

        repo = InMemoryBeatmapStore()
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
        repo = InMemoryBeatmapStore()
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
        repo = InMemoryBeatmapStore()
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
        repo = InMemoryBeatmapStore()
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
        repo = InMemoryBeatmapStore()
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
        repo = InMemoryBeatmapStore()
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
    from osu_server.domain.beatmaps import Beatmap  # noqa: PLC0415

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


# ---------------------------------------------------------------------------
# FetchBeatmapFileUseCase tests
# ---------------------------------------------------------------------------


@dataclass
class StubFileProvider:
    """Conforms to ``BeatmapFileProvider``. Returns ``OsuFileFetchResult`` or raises."""

    by_beatmap_id: dict[int, OsuFileFetchResult] = field(default_factory=dict)
    exception: Exception | None = None
    delay: float = 0
    calls: list[int] = field(default_factory=list)

    async def fetch_osu_file(self, beatmap_id: int) -> OsuFileFetchResult:
        self.calls.append(beatmap_id)
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.exception is not None:
            raise self.exception
        result = self.by_beatmap_id.get(beatmap_id)
        if result is None:
            raise ValueError(f"No file configured for beatmap_id={beatmap_id}")
        return result


@dataclass
class StubBlobStorageService:
    """Simple stub that returns ``BlobStored`` results."""

    next_blob_id: int = 1
    stored: list[Blob] = field(default_factory=list)

    async def put_bytes(self, data: bytes, *, content_type: str) -> BlobStored:
        from osu_server.domain.storage.blobs import BlobStored  # noqa: PLC0415

        blob = Blob(
            id=self.next_blob_id,
            sha256=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            content_type=content_type,
            storage_backend="stub",
            storage_key=f"stub/{self.next_blob_id}",
            created_at=_NOW,
        )
        self.next_blob_id += 1
        self.stored.append(blob)
        return BlobStored(blob=blob)


async def _setup_repo_with_beatmap(
    repo: InMemoryBeatmapStore,
    *,
    beatmap_id: int = 2000,
    beatmapset_id: int = 1000,
    checksum_md5: str = _DEFAULT_CHECKSUM,
) -> Beatmap:
    """Save a minimal beatmap into the repository and return it."""
    from osu_server.domain.beatmaps import (  # noqa: PLC0415
        Beatmap,
        BeatmapFileState,
        BeatmapMetadataSource,
        BeatmapRankStatus,
        BeatmapSet,
        BeatmapSourceVerification,
    )

    bm = Beatmap(
        id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=checksum_md5,
        mode="osu",
        version="Another",
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
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    beatmapset = BeatmapSet(
        id=beatmapset_id,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        creator="Realazy",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(bm,),
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    await repo.save_beatmapset_snapshot(beatmapset)
    return bm


_FILE_BODY = b"osu file format v14\n[General]\nAudioFilename: audio.mp3\n"
_FILE_BODY_MD5 = "c76db67ba86527673e81495b1602f24b"
_FILE_BODY_MISMATCH = b"osu file format v14\n[General]\nAudioFilename: wrong.mp3\n"


class TestFetchBeatmapFileUseCase:
    """Idempotent .osu file fetch job behaviour."""

    @staticmethod
    def _make_job(
        repo: InMemoryBeatmapStore,
        file_provider: StubFileProvider | None = None,
        blob_storage: StubBlobStorageService | None = None,
    ) -> FetchBeatmapFileUseCase:
        _provider: StubFileProvider = file_provider or StubFileProvider()
        _blob: StubBlobStorageService = blob_storage or StubBlobStorageService()
        return FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=_provider,
            blob_storage=_blob,
        )

    # --- success path --------------------------------------------------------

    async def test_successful_file_fetch_verifies_and_attaches(self) -> None:
        """File is fetched, md5 verified, blob stored, and attachment attached."""
        repo = InMemoryBeatmapStore()
        _ = await _setup_repo_with_beatmap(repo, checksum_md5=_FILE_BODY_MD5)
        expected_md5 = _FILE_BODY_MD5
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        blob_storage = StubBlobStorageService()
        job = self._make_job(repo, file_provider=file_provider, blob_storage=blob_storage)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        await job.execute(target)

        # File provider was called once
        assert len(file_provider.calls) == 1
        assert file_provider.calls[0] == 2000

        # Blob was stored
        assert len(blob_storage.stored) == 1
        assert blob_storage.stored[0].byte_size == len(_FILE_BODY)

        # Attachment is attached
        attachment = await repo.get_current_file_attachment(2000)
        assert attachment is not None
        assert attachment.blob_id == blob_storage.stored[0].id
        assert attachment.checksum_md5 == expected_md5
        assert attachment.source == BeatmapFileSource.OSU_CURRENT.value
        assert attachment.original_filename == "2000.osu"
        assert attachment.fetched_at is not None
        assert attachment.verified_at is not None

        # Fetch state is succeeded
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    # --- checksum mismatch ---------------------------------------------------

    async def test_checksum_mismatch_marks_failed(self) -> None:
        """When fetched bytes don't match expected md5, fetch is marked failed
        and no blob is stored."""
        repo = InMemoryBeatmapStore()
        _ = await _setup_repo_with_beatmap(repo, checksum_md5=_DEFAULT_CHECKSUM)
        # _FILE_BODY_MISMATCH has a different md5 than _DEFAULT_CHECKSUM
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY_MISMATCH,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        blob_storage = StubBlobStorageService()
        job = self._make_job(repo, file_provider=file_provider, blob_storage=blob_storage)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        await job.execute(target)

        # No blob was stored
        assert len(blob_storage.stored) == 0

        # No attachment exists
        attachment = await repo.get_current_file_attachment(2000)
        assert attachment is None

        # Fetch state is failed with checksum mismatch detail
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED
        assert fetch_record.last_error is not None
        assert "checksum mismatch" in fetch_record.last_error.lower()

        # The beatmap's file_state is still the original (unchanged)
        saved_beatmap = await repo.get_beatmap(2000)
        assert saved_beatmap is not None
        assert saved_beatmap.file_state is BeatmapFileState.MISSING

    # --- idempotency ---------------------------------------------------------

    async def test_already_pending_skips_fetch(self) -> None:
        """When the target is already in PENDING_FETCH state, the job returns
        without contacting the file provider."""
        repo = InMemoryBeatmapStore()
        _ = await _setup_repo_with_beatmap(repo)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)
        # Pre-mark as pending
        _ = await repo.try_mark_fetch_pending(target, _NOW)

        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        job = self._make_job(repo, file_provider=file_provider)

        await job.execute(target)

        # The file provider was never called
        assert len(file_provider.calls) == 0

    async def test_duplicate_verified_file_reuses_existing_attachment(self) -> None:
        """Existing verified attachment marks the fetch succeeded without storing again."""
        repo = InMemoryBeatmapStore()
        _ = await _setup_repo_with_beatmap(repo, checksum_md5=_FILE_BODY_MD5)
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        blob_storage = StubBlobStorageService()
        job = self._make_job(repo, file_provider=file_provider, blob_storage=blob_storage)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        await job.execute(target)
        first_attachment = await repo.get_current_file_attachment(2000)
        await job.execute(target)
        second_attachment = await repo.get_current_file_attachment(2000)

        assert first_attachment is not None
        assert second_attachment == first_attachment
        assert len(file_provider.calls) == 1
        assert len(blob_storage.stored) == 1
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    async def test_concurrent_calls_only_one_proceeds(self) -> None:
        """Two concurrent calls for the same target: the second skips."""
        repo = InMemoryBeatmapStore()
        _ = await _setup_repo_with_beatmap(repo, checksum_md5=_FILE_BODY_MD5)
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(
            by_beatmap_id={2000: fetch_result},
            delay=0.05,
        )
        blob_storage = StubBlobStorageService()
        job = self._make_job(repo, file_provider=file_provider, blob_storage=blob_storage)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        _ = await asyncio.gather(
            job.execute(target),
            job.execute(target),
        )

        # The file provider was called only once
        assert len(file_provider.calls) == 1
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    # --- beatmap not found ---------------------------------------------------

    async def test_beatmap_not_found_marks_failed(self) -> None:
        """When the beatmap doesn't exist in the repository, the fetch is marked
        failed without contacting the file provider."""
        repo = InMemoryBeatmapStore()
        # Do NOT set up any beatmap
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        job = self._make_job(repo, file_provider=file_provider)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        await job.execute(target)

        # The file provider was never called
        assert len(file_provider.calls) == 0
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED

    # --- provider failure ----------------------------------------------------

    async def test_file_provider_raises_marks_failed(self) -> None:
        """When the file provider raises, the fetch is marked failed and no blob
        is stored."""
        repo = InMemoryBeatmapStore()
        _ = await _setup_repo_with_beatmap(repo)
        file_provider = StubFileProvider(exception=RuntimeError("mirror down"))
        blob_storage = StubBlobStorageService()
        job = self._make_job(repo, file_provider=file_provider, blob_storage=blob_storage)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        await job.execute(target)

        # No blob was stored
        assert len(blob_storage.stored) == 0
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED
        assert fetch_record.last_error is not None
        assert "mirror down" in fetch_record.last_error
