"""Structured logging tests for beatmap fetch jobs.

Covers:
- ``FetchBeatmapMetadataJob`` start, success, failure, mirror fallback events.
- ``FetchBeatmapFileJob`` start, success, failure, checksum mismatch events.
- Redaction of sensitive values (API credentials, authorization) from log fields.

All tests use ``structlog.testing.capture_logs()`` to verify event names
and key fields without depending on the logging sink configuration.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from structlog.testing import capture_logs

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
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
from osu_server.domain.storage.blobs import Blob, BlobStored
from osu_server.jobs.beatmap_fetch import FetchBeatmapFileJob, FetchBeatmapMetadataJob
from osu_server.repositories.beatmaps.metadata_providers import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.repositories.interfaces.beatmap_repository import (
    BeatmapFetchTarget,
)
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository

_NOW = datetime(2026, 6, 5, tzinfo=UTC)
_THIRTY_DAYS = timedelta(days=30)
_DEFAULT_CHECKSUM = "0123456789abcdef0123456789abcdef"


# ---------------------------------------------------------------------------
# Stub providers (same pattern as test_beatmap_fetch.py)
# ---------------------------------------------------------------------------


@dataclass
class StubMetadataProvider:
    """Simple in-memory provider for log capture tests."""

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


@dataclass
class StubFileProvider:
    """Simple stub file provider for log capture tests."""

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
    """Simple stub blob storage for log capture tests."""

    next_blob_id: int = 1
    stored: list[Blob] = field(default_factory=list)

    async def put_bytes(self, data: bytes, *, content_type: str) -> BlobStored:
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
            checksum_md5=checksum_md5 if i == 0 else "abcdef0123456789abcdef0123456789",
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


_FILE_BODY = b"osu file format v14\n[General]\nAudioFilename: audio.mp3\n"
_FILE_BODY_MD5 = "c76db67ba86527673e81495b1602f24b"
_FILE_BODY_MISMATCH = b"osu file format v14\n[General]\nAudioFilename: wrong.mp3\n"


# ---------------------------------------------------------------------------
# Metadata fetch job logging tests
# ---------------------------------------------------------------------------


class TestMetadataFetchJobLogging:
    """Structured observability for ``FetchBeatmapMetadataJob``."""

    @staticmethod
    def _make_job(
        repo: InMemoryBeatmapRepository,
        official: StubMetadataProvider | None = None,
        mirror: StubMetadataProvider | None = None,
    ) -> FetchBeatmapMetadataJob:
        _official = official or StubMetadataProvider()
        _mirror = mirror or StubMetadataProvider()
        composite = CompositeBeatmapMetadataProvider(official=_official, mirror=_mirror)
        return FetchBeatmapMetadataJob(repository=repo, metadata_provider=composite)

    async def test_logs_start_and_success_for_beatmap_id(self) -> None:
        """Metadata fetch logs started and succeeded events with target and source."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        started = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_started"]
        assert len(started) == 1
        assert started[0]["target_type"] == "metadata:beatmap"
        assert started[0]["target_key"] == "2000"

        succeeded = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_succeeded"]
        assert len(succeeded) == 1
        assert succeeded[0]["target_type"] == "metadata:beatmap"
        assert succeeded[0]["target_key"] == "2000"
        assert succeeded[0]["beatmapset_id"] == snapshot.beatmapset_id
        assert succeeded[0]["source"] == BeatmapMetadataSource.OFFICIAL.value

    async def test_logs_start_and_success_for_checksum(self) -> None:
        """Metadata fetch logs started and succeeded events for checksum lookup."""
        repo = InMemoryBeatmapRepository()
        checksum = _DEFAULT_CHECKSUM
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_checksum={checksum: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_checksum(checksum)

        with capture_logs() as logs:
            await job.execute(target)

        succeeded = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_succeeded"]
        assert len(succeeded) == 1
        assert succeeded[0]["target_type"] == "metadata:checksum"
        assert succeeded[0]["target_key"] == checksum

    async def test_logs_failure_when_all_sources_fail(self) -> None:
        """Metadata fetch logs a failure event when no provider returns a result."""
        repo = InMemoryBeatmapRepository()
        official = StubMetadataProvider()
        mirror = StubMetadataProvider()
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        failed = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_failed"]
        assert len(failed) == 1
        assert failed[0]["target_type"] == "metadata:beatmap"
        assert failed[0]["target_key"] == "2000"
        assert "error" in failed[0]

    async def test_logs_failure_when_all_providers_raise(self) -> None:
        """Metadata fetch logs a failure event when all providers raise."""
        repo = InMemoryBeatmapRepository()
        official = StubMetadataProvider(exception=RuntimeError("official down"))
        mirror = StubMetadataProvider(exception=RuntimeError("mirror down"))
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        failed = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_failed"]
        assert len(failed) == 1

    async def test_logs_mirror_fallback_when_official_returns_none(self) -> None:
        """Mirror fallback is logged when official returns None and mirror succeeds."""
        repo = InMemoryBeatmapRepository()
        mirror_snapshot = _make_mirror_snapshot()
        official = StubMetadataProvider()
        mirror = StubMetadataProvider(by_beatmap_id={2000: mirror_snapshot})
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        mirror_events = [e for e in logs if e.get("event") == "beatmap_mirror_fallback_used"]
        assert len(mirror_events) == 1
        assert mirror_events[0]["source_type"] == "metadata"
        assert mirror_events[0]["key_kind"] == "beatmap_id"
        assert mirror_events[0]["key"] == "2000"

    async def test_logs_mirror_fallback_when_official_raises(self) -> None:
        """Mirror fallback is logged when official raises and mirror succeeds."""
        repo = InMemoryBeatmapRepository()
        mirror_snapshot = _make_mirror_snapshot()
        official = StubMetadataProvider(exception=RuntimeError("official down"))
        mirror = StubMetadataProvider(by_beatmap_id={2000: mirror_snapshot})
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        mirror_events = [e for e in logs if e.get("event") == "beatmap_mirror_fallback_used"]
        assert len(mirror_events) == 1
        assert mirror_events[0]["source_type"] == "metadata"

    async def test_does_not_log_mirror_fallback_when_official_succeeds(self) -> None:
        """No mirror fallback event when official provider succeeds."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        mirror = StubMetadataProvider()
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        mirror_events = [e for e in logs if e.get("event") == "beatmap_mirror_fallback_used"]
        assert len(mirror_events) == 0

    async def test_no_api_credentials_in_logs(self) -> None:
        """Log events must not include API credentials, tokens, or authorization values."""
        repo = InMemoryBeatmapRepository()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        sensitive_fields = {
            "api_key",
            "api_token",
            "token",
            "secret",
            "credential",
            "authorization",
            "password",
            "password_hash",
            "password_md5",
            "api_secret",
            "access_token",
            "bearer",
            "apikey",
            "client_secret",
        }

        for entry in logs:
            for key in entry:
                lower_key = key.lower()
                for sensitive in sensitive_fields:
                    assert sensitive not in lower_key, (
                        f"Sensitive field '{key}' found in log event '{entry.get('event')}'"
                    )


# ---------------------------------------------------------------------------
# File fetch job logging tests
# ---------------------------------------------------------------------------


class TestFileFetchJobLogging:
    """Structured observability for ``FetchBeatmapFileJob``."""

    @staticmethod
    async def _setup_repo_with_beatmap(
        repo: InMemoryBeatmapRepository,
        *,
        beatmap_id: int = 2000,
        beatmapset_id: int = 1000,
        checksum_md5: str = _DEFAULT_CHECKSUM,
    ) -> None:
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

    @staticmethod
    def _make_job(
        repo: InMemoryBeatmapRepository,
        file_provider: StubFileProvider | None = None,
        blob_storage: StubBlobStorageService | None = None,
    ) -> FetchBeatmapFileJob:
        _provider = file_provider or StubFileProvider()
        _blob = blob_storage or StubBlobStorageService()
        return FetchBeatmapFileJob(
            repository=repo,
            file_provider=_provider,
            blob_storage=_blob,
        )

    async def test_logs_start_and_success(self) -> None:
        """File fetch logs started and succeeded events with target and source."""
        repo = InMemoryBeatmapRepository()
        await self._setup_repo_with_beatmap(repo, checksum_md5=_FILE_BODY_MD5)
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        job = self._make_job(repo, file_provider=file_provider)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        started = [e for e in logs if e.get("event") == "beatmap_file_fetch_started"]
        assert len(started) == 1
        assert started[0]["target_type"] == "file:beatmap"
        assert started[0]["target_key"] == "2000"

        succeeded = [e for e in logs if e.get("event") == "beatmap_file_fetch_succeeded"]
        assert len(succeeded) == 1
        assert succeeded[0]["target_type"] == "file:beatmap"
        assert succeeded[0]["target_key"] == "2000"
        assert succeeded[0]["beatmap_id"] == 2000
        assert succeeded[0]["source"] == BeatmapFileSource.OSU_CURRENT.value

    async def test_logs_failure_when_provider_raises(self) -> None:
        """File fetch logs a failure event when the file provider raises."""
        repo = InMemoryBeatmapRepository()
        await self._setup_repo_with_beatmap(repo)
        file_provider = StubFileProvider(exception=RuntimeError("mirror down"))
        job = self._make_job(repo, file_provider=file_provider)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        failed = [e for e in logs if e.get("event") == "beatmap_file_fetch_failed"]
        assert len(failed) == 1
        assert failed[0]["target_type"] == "file:beatmap"
        assert failed[0]["target_key"] == "2000"
        assert "error" in failed[0]

    async def test_logs_checksum_mismatch(self) -> None:
        """File fetch logs a checksum mismatch event when fetched bytes don't match."""
        repo = InMemoryBeatmapRepository()
        await self._setup_repo_with_beatmap(repo, checksum_md5=_DEFAULT_CHECKSUM)
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY_MISMATCH,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        job = self._make_job(repo, file_provider=file_provider)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        mismatch = [e for e in logs if e.get("event") == "beatmap_file_checksum_mismatch"]
        assert len(mismatch) == 1
        assert mismatch[0]["beatmap_id"] == 2000
        # Expected and actual checksums should be present (actual is redacted from full value)
        assert "expected_md5_prefix" in mismatch[0]
        assert mismatch[0]["expected_md5_prefix"] == _DEFAULT_CHECKSUM[:8]

        # The checksum mismatch should also log a failure
        failed = [e for e in logs if e.get("event") == "beatmap_file_fetch_failed"]
        assert len(failed) == 1

    async def test_logs_failure_when_beatmap_not_found(self) -> None:
        """File fetch logs failure when beatmap does not exist in repo."""
        repo = InMemoryBeatmapRepository()
        file_provider = StubFileProvider()
        job = self._make_job(repo, file_provider=file_provider)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        failed = [e for e in logs if e.get("event") == "beatmap_file_fetch_failed"]
        assert len(failed) == 1

    # (test_no_api_credentials_in_logs moved to TestMetadataFetchJobLogging)
