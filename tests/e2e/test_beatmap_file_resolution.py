"""E2E tests for .osu file availability resolution flow.

Exercises the full file fetch pipeline: missing file state, file fetch job
completion, md5 verification against expected beatmap checksum, blob storage
write, attachment availability, community mirror fallback, and checksum
mismatch rejection.  Uses in-memory repositories, stub file providers, and
stub blob storage -- no real network credentials required.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapFreshnessPolicy,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
    OsuFileFetchResult,
)
from osu_server.domain.storage.blobs import Blob
from osu_server.infrastructure.beatmaps.metadata_sources import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
)
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)
from tests.support.beatmaps import InMemoryBeatmapStore

if TYPE_CHECKING:
    from osu_server.domain.storage.blobs import BlobStored

_ONE_HOUR = timedelta(hours=1)
_THIRTY_DAYS = timedelta(days=30)
_NOW = datetime.now(UTC)

_BEATMAP_ID = 3000
_BEATMAPSET_ID = 1500
_CHECKSUM = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"

_FILE_BODY = b"osu file format v14\n\n[General]\nAudioFilename: song.mp3\n"
_FILE_BODY_MD5 = hashlib.md5(_FILE_BODY, usedforsecurity=False).hexdigest()


# ---------------------------------------------------------------------------
# Snapshot factories
# ---------------------------------------------------------------------------


def _make_osu_file_result(
    *,
    beatmap_id: int = _BEATMAP_ID,
    body: bytes = _FILE_BODY,
    source: BeatmapFileSource = BeatmapFileSource.OSU_CURRENT,
    original_filename: str | None = f"{_BEATMAP_ID}.osu",
) -> OsuFileFetchResult:
    return OsuFileFetchResult(
        beatmap_id=beatmap_id,
        body=body,
        source=source,
        original_filename=original_filename,
    )


def _make_snapshot(
    *,
    beatmap_id: int = _BEATMAP_ID,
    beatmapset_id: int = _BEATMAPSET_ID,
    checksum_md5: str = _FILE_BODY_MD5,
    artist: str = "xi",
    title: str = "Freedom Dive",
    creator: str = "Nakagawa-Kanon",
) -> BeatmapsetSnapshot:
    bm = BeatmapSnapshot(
        beatmap_id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=checksum_md5,
        mode="osu",
        version="Another",
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist=artist,
        title=title,
        creator=creator,
        source=BeatmapMetadataSource.OFFICIAL,
        verified=BeatmapSourceVerification.VERIFIED,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(bm,),
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )


def _make_freshness_policy() -> BeatmapFreshnessPolicy:
    return BeatmapFreshnessPolicy(
        ranked_refresh_interval=_THIRTY_DAYS,
        pending_refresh_interval=_ONE_HOUR,
        graveyard_refresh_interval=_THIRTY_DAYS,
        mirror_refresh_interval=_ONE_HOUR,
    )


# ---------------------------------------------------------------------------
# Stub doubles
# ---------------------------------------------------------------------------


@dataclass
class StubFileProvider:
    """Conforms to ``BeatmapFileProvider``. Returns pre-configured results or raises."""

    by_beatmap_id: dict[int, OsuFileFetchResult] = field(default_factory=dict)
    exception: Exception | None = None
    calls: list[int] = field(default_factory=list)

    async def fetch_osu_file(self, beatmap_id: int) -> OsuFileFetchResult:
        self.calls.append(beatmap_id)
        if self.exception is not None:
            raise self.exception
        result = self.by_beatmap_id.get(beatmap_id)
        if result is None:
            raise ValueError(f"No file configured for beatmap_id={beatmap_id}")
        return result


@dataclass
class StubMetadataProvider:
    """Conforms to ``BeatmapMetadataProvider``. Returns pre-configured snapshots."""

    by_beatmap_id: dict[int, BeatmapsetSnapshot | None] = field(default_factory=dict)
    by_beatmapset_id: dict[int, BeatmapsetSnapshot | None] = field(default_factory=dict)
    by_checksum: dict[str, BeatmapsetSnapshot | None] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        self.calls.append(f"beatmap_id:{beatmap_id}")
        return self.by_beatmap_id.get(beatmap_id)

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        self.calls.append(f"beatmapset_id:{beatmapset_id}")
        return self.by_beatmapset_id.get(beatmapset_id)

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        self.calls.append(f"checksum:{checksum_md5}")
        return self.by_checksum.get(checksum_md5)


@dataclass
class StubBlobStorageService:
    """Stub blob storage that records stored blobs and returns ``BlobStored``."""

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


# ---------------------------------------------------------------------------
# Wiring helper
# ---------------------------------------------------------------------------


def _build_service(
    repo: InMemoryBeatmapStore,
    *,
    mirror_trust_enabled: bool = False,
) -> tuple[BeatmapMirrorService, list[BeatmapFetchTarget]]:
    """Wire a service with a spy-based enqueue callback."""
    enqueued: list[BeatmapFetchTarget] = []

    async def _enqueue(target: BeatmapFetchTarget) -> None:
        enqueued.append(target)

    service = BeatmapMirrorService(
        repository=repo.query_repository,
        eligibility_service=BeatmapEligibilityService(),
        freshness_policy=_make_freshness_policy(),
        mirror_trust_enabled=mirror_trust_enabled,
        enqueue_refresh=_enqueue,
    )
    return service, enqueued


async def _save_beatmap_metadata(
    repo: InMemoryBeatmapStore,
    *,
    beatmap_id: int = _BEATMAP_ID,
    checksum_md5: str = _FILE_BODY_MD5,
) -> None:
    """Save beatmap metadata into the repository via a metadata job."""
    snapshot = _make_snapshot(beatmap_id=beatmap_id, checksum_md5=checksum_md5)
    metadata_provider = StubMetadataProvider(by_beatmap_id={beatmap_id: snapshot})
    composite = CompositeBeatmapMetadataProvider(
        official=metadata_provider,
        mirror=StubMetadataProvider(),
    )
    metadata_job = FetchBeatmapMetadataUseCase(
        uow_factory=repo.uow_factory,
        metadata_provider=composite,
        freshness_policy=_make_freshness_policy(),
    )
    target = BeatmapFetchTarget.metadata_by_beatmap_id(beatmap_id)
    await metadata_job.execute(target)


# ---------------------------------------------------------------------------
# Tests: missing file → fetch → available
# ---------------------------------------------------------------------------


class TestFileResolutionE2E:
    @pytest.mark.asyncio
    async def test_missing_file_transitions_to_available_after_fetch(self) -> None:
        """Beatmap metadata is cached but .osu file is missing.  After resolve
        enqueues a file fetch and the job completes, the file is available with
        verified checksum and source recorded."""
        repo = InMemoryBeatmapStore()
        await _save_beatmap_metadata(repo)

        service, enqueued = _build_service(repo)

        # --- First resolve with require_osu_file: file is MISSING ---------------
        result1 = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )

        assert result1.beatmap is not None
        assert result1.beatmap.id == _BEATMAP_ID
        assert result1.metadata_status is BeatmapFetchState.FRESH
        assert result1.file_status is BeatmapFileState.MISSING
        # A file fetch was enqueued
        file_enqueues = [t for t in enqueued if t.target_type == "file:beatmap"]
        assert len(file_enqueues) == 1
        assert file_enqueues[0].target_key == str(_BEATMAP_ID)

        # --- Execute the file fetch job -----------------------------------------
        fetch_result = _make_osu_file_result()
        file_provider = StubFileProvider(by_beatmap_id={_BEATMAP_ID: fetch_result})
        blob_storage = StubBlobStorageService()
        file_job = FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=file_provider,
            blob_storage=blob_storage,
        )
        await file_job.execute(file_enqueues[0])

        # --- Second resolve: file is now AVAILABLE ------------------------------
        result2 = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )

        assert result2.beatmap is not None
        assert result2.file_status is BeatmapFileState.AVAILABLE
        assert result2.reason is None  # no complaint about missing file

        # Blob was stored
        assert len(blob_storage.stored) == 1
        assert blob_storage.stored[0].byte_size == len(_FILE_BODY)

        # Attachment is attached with correct data
        attachment = await repo.get_current_file_attachment(_BEATMAP_ID)
        assert attachment is not None
        assert attachment.checksum_md5 == _FILE_BODY_MD5
        assert attachment.source == BeatmapFileSource.OSU_CURRENT.value
        assert attachment.original_filename == f"{_BEATMAP_ID}.osu"

    @pytest.mark.asyncio
    async def test_file_resolve_without_require_flag_does_not_enqueue_file(self) -> None:
        """When require_osu_file is False (default), resolve does not enqueue a
        file fetch even when the file is missing."""
        repo = InMemoryBeatmapStore()
        await _save_beatmap_metadata(repo)

        service, enqueued = _build_service(repo)

        result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result.beatmap is not None
        assert result.metadata_status is BeatmapFetchState.FRESH
        assert result.file_status is BeatmapFileState.MISSING
        # No file fetch was enqueued
        file_enqueues = [t for t in enqueued if t.target_type == "file:beatmap"]
        assert len(file_enqueues) == 0

    @pytest.mark.asyncio
    async def test_unknown_beatmap_require_osu_file_returns_missing(self) -> None:
        """An unknown beatmap with require_osu_file returns file MISSING and
        enqueues both metadata and file fetches."""
        repo = InMemoryBeatmapStore()
        service, enqueued = _build_service(repo)

        result = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )

        assert result.beatmap is None
        assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
        assert result.file_status is BeatmapFileState.MISSING
        assert result.reason == "unsolicited"

        file_enqueues = [t for t in enqueued if t.target_type == "file:beatmap"]
        metadata_enqueues = [t for t in enqueued if t.target_type.startswith("metadata:")]
        assert len(file_enqueues) == 1
        assert len(metadata_enqueues) == 1


# ---------------------------------------------------------------------------
# Tests: md5 verification and checksum mismatch
# ---------------------------------------------------------------------------


class TestFileChecksumVerificationE2E:
    @pytest.mark.asyncio
    async def test_checksum_mismatch_rejects_file(self) -> None:
        """When the fetched file body does not match the expected md5 checksum,
        the file fetch is marked failed and the file remains MISSING."""
        repo = InMemoryBeatmapStore()
        await _save_beatmap_metadata(repo)

        service, enqueued = _build_service(repo)

        # Enqueue file fetch
        _ = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )
        file_enqueues = [t for t in enqueued if t.target_type == "file:beatmap"]

        # Execute file job with mismatched body
        mismatched_body = b"osu file format v14\n\n[General]\nAudioFilename: wrong.mp3\n"
        fetch_result = _make_osu_file_result(body=mismatched_body)
        file_provider = StubFileProvider(by_beatmap_id={_BEATMAP_ID: fetch_result})
        blob_storage = StubBlobStorageService()
        file_job = FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=file_provider,
            blob_storage=blob_storage,
        )
        await file_job.execute(file_enqueues[0])

        # No blob was stored
        assert len(blob_storage.stored) == 0

        # File is still MISSING (unchanged beatmap state)
        beatmap = await repo.get_beatmap(_BEATMAP_ID)
        assert beatmap is not None
        assert beatmap.file_state is BeatmapFileState.MISSING

        # Resolve again: file still MISSING, metadata still FRESH
        result = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )

        assert result.beatmap is not None
        assert result.metadata_status is BeatmapFetchState.FRESH
        assert result.file_status is BeatmapFileState.MISSING
        assert result.reason == "osu_file_required_but_unavailable"

    @pytest.mark.asyncio
    async def test_fetch_marks_failed_state_on_checksum_mismatch(self) -> None:
        """The file fetch state is marked FAILED after checksum mismatch."""
        repo = InMemoryBeatmapStore()
        await _save_beatmap_metadata(repo)

        file_target = BeatmapFetchTarget.file_by_beatmap_id(_BEATMAP_ID)

        mismatched_body = b"completely different content\n"
        fetch_result = _make_osu_file_result(body=mismatched_body)
        file_provider = StubFileProvider(by_beatmap_id={_BEATMAP_ID: fetch_result})
        file_job = FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=file_provider,
            blob_storage=StubBlobStorageService(),
        )
        await file_job.execute(file_target)

        fetch_record = await repo.get_fetch_state(file_target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED
        assert fetch_record.last_error is not None
        assert "checksum mismatch" in fetch_record.last_error.lower()


# ---------------------------------------------------------------------------
# Tests: community mirror fallback
# ---------------------------------------------------------------------------


class TestFileMirrorFallbackE2E:
    @pytest.mark.asyncio
    async def test_mirror_fallback_records_community_mirror_source(self) -> None:
        """When direct sources fail (simulated) and a community mirror provides
        the file, the attachment records the COMMUNITY_MIRROR source and the
        file is available."""
        repo = InMemoryBeatmapStore()
        await _save_beatmap_metadata(repo)

        service, enqueued = _build_service(repo)

        # Enqueue file fetch
        _ = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )
        file_enqueues = [t for t in enqueued if t.target_type == "file:beatmap"]

        # Simulate mirror fallback: file provider returns COMMUNITY_MIRROR source
        fetch_result = _make_osu_file_result(
            source=BeatmapFileSource.COMMUNITY_MIRROR,
            original_filename=None,
        )
        file_provider = StubFileProvider(by_beatmap_id={_BEATMAP_ID: fetch_result})
        blob_storage = StubBlobStorageService()
        file_job = FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=file_provider,
            blob_storage=blob_storage,
        )
        await file_job.execute(file_enqueues[0])

        # File is available with mirror source
        beatmap = await repo.get_beatmap(_BEATMAP_ID)
        assert beatmap is not None
        assert beatmap.file_state is BeatmapFileState.AVAILABLE

        attachment = await repo.get_current_file_attachment(_BEATMAP_ID)
        assert attachment is not None
        assert attachment.checksum_md5 == _FILE_BODY_MD5
        assert attachment.source == BeatmapFileSource.COMMUNITY_MIRROR.value
        # Mirror may not provide an original filename
        assert attachment.original_filename is None

    @pytest.mark.asyncio
    async def test_after_mirror_file_fetch_service_reports_available(self) -> None:
        """After a mirror-sourced file fetch completes, the service reports
        the file as available on the next resolve."""
        repo = InMemoryBeatmapStore()
        await _save_beatmap_metadata(repo)

        service, enqueued = _build_service(repo)

        _ = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )
        file_enqueues = [t for t in enqueued if t.target_type == "file:beatmap"]

        fetch_result = _make_osu_file_result(
            source=BeatmapFileSource.COMMUNITY_MIRROR,
        )
        file_provider = StubFileProvider(by_beatmap_id={_BEATMAP_ID: fetch_result})
        file_job = FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=file_provider,
            blob_storage=StubBlobStorageService(),
        )
        await file_job.execute(file_enqueues[0])

        result = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )

        assert result.beatmap is not None
        assert result.file_status is BeatmapFileState.AVAILABLE
        assert result.beatmap.file_state is BeatmapFileState.AVAILABLE
        assert result.reason is None

    @pytest.mark.asyncio
    async def test_rate_limited_direct_source_fallback_to_mirror(self) -> None:
        """Simulate direct source rate limiting: a stub provider that raises
        a simulated failure is a simplified representation of the composite
        provider's 429 fallback.  The file job should handle the provider
        failing and mark the fetch as failed.  Then a second provider
        (mirror) can succeed.

        This test exercises the architecture where the composite provider
        handles fallback internally; here we model the outcome: the resolved
        file shows COMMUNITY_MIRROR source after attachment.
        """
        repo = InMemoryBeatmapStore()
        await _save_beatmap_metadata(repo)

        service, enqueued = _build_service(repo)

        _ = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )
        file_enqueues = [t for t in enqueued if t.target_type == "file:beatmap"]

        # First attempt: provider fails (simulating rate limit on all direct sources)
        failing_provider = StubFileProvider(exception=RuntimeError("429 Too Many Requests"))
        blob_storage = StubBlobStorageService()
        file_job = FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=failing_provider,
            blob_storage=blob_storage,
        )
        await file_job.execute(file_enqueues[0])

        # File fetch is marked failed
        fetch_record = await repo.get_fetch_state(file_enqueues[0])
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED

        # Second attempt simulates retry through mirror.  The job's own
        # try_mark_fetch_pending transitions from FAILED to PENDING_FETCH
        # since it is not already pending.
        mirror_result = _make_osu_file_result(source=BeatmapFileSource.COMMUNITY_MIRROR)
        mirror_provider = StubFileProvider(by_beatmap_id={_BEATMAP_ID: mirror_result})
        mirror_job = FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=mirror_provider,
            blob_storage=StubBlobStorageService(),
        )
        await mirror_job.execute(file_enqueues[0])

        # After mirror succeeds: file available with mirror source
        beatmap = await repo.get_beatmap(_BEATMAP_ID)
        assert beatmap is not None
        assert beatmap.file_state is BeatmapFileState.AVAILABLE

        attachment = await repo.get_current_file_attachment(_BEATMAP_ID)
        assert attachment is not None
        # The source reflects the mirror, not the original rate-limited attempt
        assert attachment.source == BeatmapFileSource.COMMUNITY_MIRROR.value

        result = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )
        assert result.file_status is BeatmapFileState.AVAILABLE


# ---------------------------------------------------------------------------
# Tests: blob storage attachment (req 6.5)
# ---------------------------------------------------------------------------


class TestFileBlobStorageIntegrationE2E:
    @pytest.mark.asyncio
    async def test_file_body_stored_through_blob_storage_not_embedded(self) -> None:
        """The file body is stored through the blob storage service; the beatmap
        metadata references a blob id, not the raw file bytes."""
        repo = InMemoryBeatmapStore()
        await _save_beatmap_metadata(repo)

        service, enqueued = _build_service(repo)

        _ = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )
        file_enqueues = [t for t in enqueued if t.target_type == "file:beatmap"]

        fetch_result = _make_osu_file_result()
        blob_storage = StubBlobStorageService()
        file_job = FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=StubFileProvider(by_beatmap_id={_BEATMAP_ID: fetch_result}),
            blob_storage=blob_storage,
        )
        await file_job.execute(file_enqueues[0])

        # Blob storage received the file body
        assert len(blob_storage.stored) == 1
        stored_blob = blob_storage.stored[0]
        assert stored_blob.byte_size == len(_FILE_BODY)
        assert stored_blob.content_type == "application/x-osu-beatmap"

        # Beatmap attachment references the blob
        attachment = await repo.get_current_file_attachment(_BEATMAP_ID)
        assert attachment is not None
        assert attachment.blob_id == stored_blob.id
        assert attachment.checksum_md5 == _FILE_BODY_MD5

        # The beatmap itself does not contain raw file bytes
        beatmap = await repo.get_beatmap(_BEATMAP_ID)
        assert beatmap is not None
        assert beatmap.file_attachment is not None
        # blob_id is an int, not the file body bytes
        assert isinstance(beatmap.file_attachment.blob_id, int)


# ---------------------------------------------------------------------------
# Tests: file source tracking (req 6.8, 16.3)
# ---------------------------------------------------------------------------


class TestFileSourceTrackingE2E:
    @pytest.mark.asyncio
    async def test_osu_current_source_recorded_in_attachment(self) -> None:
        """When the file is fetched from osu_current, the attachment records
        the correct source."""
        repo = InMemoryBeatmapStore()
        await _save_beatmap_metadata(repo)

        file_target = BeatmapFetchTarget.file_by_beatmap_id(_BEATMAP_ID)
        fetch_result = _make_osu_file_result(source=BeatmapFileSource.OSU_CURRENT)
        file_provider = StubFileProvider(by_beatmap_id={_BEATMAP_ID: fetch_result})
        file_job = FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=file_provider,
            blob_storage=StubBlobStorageService(),
        )
        await file_job.execute(file_target)

        attachment = await repo.get_current_file_attachment(_BEATMAP_ID)
        assert attachment is not None
        assert attachment.source == BeatmapFileSource.OSU_CURRENT.value

    @pytest.mark.asyncio
    async def test_osu_legacy_source_recorded_in_attachment(self) -> None:
        """When the file is fetched from osu_legacy, the attachment records
        the correct source."""
        repo = InMemoryBeatmapStore()
        await _save_beatmap_metadata(repo)

        file_target = BeatmapFetchTarget.file_by_beatmap_id(_BEATMAP_ID)
        fetch_result = _make_osu_file_result(source=BeatmapFileSource.OSU_LEGACY)
        file_provider = StubFileProvider(by_beatmap_id={_BEATMAP_ID: fetch_result})
        file_job = FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=file_provider,
            blob_storage=StubBlobStorageService(),
        )
        await file_job.execute(file_target)

        attachment = await repo.get_current_file_attachment(_BEATMAP_ID)
        assert attachment is not None
        assert attachment.source == BeatmapFileSource.OSU_LEGACY.value

    @pytest.mark.asyncio
    async def test_community_mirror_source_recorded_in_attachment(self) -> None:
        """When the file is fetched from a community mirror, the attachment
        records the correct source."""
        repo = InMemoryBeatmapStore()
        await _save_beatmap_metadata(repo)

        file_target = BeatmapFetchTarget.file_by_beatmap_id(_BEATMAP_ID)
        fetch_result = _make_osu_file_result(source=BeatmapFileSource.COMMUNITY_MIRROR)
        file_provider = StubFileProvider(by_beatmap_id={_BEATMAP_ID: fetch_result})
        file_job = FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=file_provider,
            blob_storage=StubBlobStorageService(),
        )
        await file_job.execute(file_target)

        attachment = await repo.get_current_file_attachment(_BEATMAP_ID)
        assert attachment is not None
        assert attachment.source == BeatmapFileSource.COMMUNITY_MIRROR.value


# ---------------------------------------------------------------------------
# Tests: file provider failure
# ---------------------------------------------------------------------------


class TestFileProviderFailureE2E:
    @pytest.mark.asyncio
    async def test_file_provider_raises_marks_failed_and_file_stays_missing(self) -> None:
        """When the file provider raises, the fetch is marked failed and the
        file remains missing."""
        repo = InMemoryBeatmapStore()
        await _save_beatmap_metadata(repo)

        service, enqueued = _build_service(repo)

        _ = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )
        file_enqueues = [t for t in enqueued if t.target_type == "file:beatmap"]

        failing_provider = StubFileProvider(exception=RuntimeError("network error"))
        file_job = FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=failing_provider,
            blob_storage=StubBlobStorageService(),
        )
        await file_job.execute(file_enqueues[0])

        # Fetch state is failed
        fetch_record = await repo.get_fetch_state(file_enqueues[0])
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED
        assert fetch_record.last_error is not None
        assert "network error" in fetch_record.last_error

        # File remains missing
        beatmap = await repo.get_beatmap(_BEATMAP_ID)
        assert beatmap is not None
        assert beatmap.file_state is BeatmapFileState.MISSING

        # Service reports missing
        result = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(require_osu_file=True),
        )
        assert result.file_status is BeatmapFileState.MISSING
        assert result.reason == "osu_file_required_but_unavailable"
