"""Tests for PP calculation beatmap file input provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileAttachment,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSourceVerification,
)
from osu_server.services.commands.scores.performance import (
    BeatmapMirrorPerformanceBeatmapFileProvider,
    PerformanceBeatmapFilePending,
    PerformanceBeatmapFilePendingReason,
    PerformanceBeatmapFileQuery,
    PerformanceBeatmapFileReady,
    PerformanceBeatmapFileUnavailable,
    PerformanceBeatmapFileUnavailableReason,
)
from osu_server.services.commands.storage.blob_storage import BlobContentUnavailableError

_NOW = datetime(2026, 6, 16, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_BEATMAP_ID = 2_000
_BEATMAPSET_ID = 1_000
_CHECKSUM = "0123456789abcdef0123456789abcdef"
_OSU_BYTES = b"osu file body"


class _Resolver:
    result: BeatmapResolveResult
    calls: list[tuple[int, BeatmapResolveOptions | None]]

    def __init__(self, result: BeatmapResolveResult) -> None:
        self.result = result
        self.calls = []

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        self.calls.append((beatmap_id, options))
        return self.result


class _BlobStorage:
    _blobs: dict[int, bytes]
    _error: OSError | None
    calls: list[int]

    def __init__(
        self,
        blobs: dict[int, bytes] | None = None,
        error: OSError | None = None,
    ) -> None:
        self._blobs = dict(blobs or {})
        self._error = error
        self.calls = []

    async def read_bytes(self, blob_id: int) -> bytes:
        self.calls.append(blob_id)
        if self._error is not None:
            raise self._error
        blob = self._blobs.get(blob_id)
        if blob is None:
            raise BlobContentUnavailableError(f"blob content is unavailable: {blob_id}")
        return blob


@pytest.mark.asyncio
async def test_provider_requests_required_osu_file_and_returns_ready_bytes() -> None:
    attachment = _make_attachment(attachment_id=7, blob_id=42)
    resolver = _Resolver(_resolve_result(_make_beatmap(file_attachment=attachment)))
    blob_storage = _BlobStorage({42: _OSU_BYTES})
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileReady)
    assert result.osu_file_bytes == _OSU_BYTES
    assert result.provenance.beatmap_id == _BEATMAP_ID
    assert result.provenance.beatmap_file_attachment_id == 7
    assert result.provenance.blob_id == 42
    assert result.provenance.checksum_md5 == _CHECKSUM
    assert blob_storage.calls == [42]
    assert len(resolver.calls) == 1
    beatmap_id, options = resolver.calls[0]
    assert beatmap_id == _BEATMAP_ID
    assert options is not None
    assert options.require_osu_file is True


@pytest.mark.asyncio
async def test_provider_treats_missing_file_as_pending_input() -> None:
    beatmap = _make_beatmap(file_state=BeatmapFileState.MISSING)
    resolver = _Resolver(_resolve_result(beatmap, file_status=BeatmapFileState.MISSING))
    blob_storage = _BlobStorage()
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFilePending)
    assert result.reason is PerformanceBeatmapFilePendingReason.OSU_FILE_MISSING
    assert result.file_status is BeatmapFileState.MISSING
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_treats_fetching_file_as_pending_input() -> None:
    beatmap = _make_beatmap(file_state=BeatmapFileState.PENDING_FETCH)
    resolver = _Resolver(_resolve_result(beatmap, file_status=BeatmapFileState.PENDING_FETCH))
    blob_storage = _BlobStorage()
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFilePending)
    assert result.reason is PerformanceBeatmapFilePendingReason.OSU_FILE_FETCH_PENDING
    assert result.file_status is BeatmapFileState.PENDING_FETCH
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_treats_unknown_pending_resolution_as_pending_input() -> None:
    resolver = _Resolver(
        _resolve_result(
            None,
            metadata_status=BeatmapFetchState.PENDING_FETCH,
            file_status=BeatmapFileState.MISSING,
            reason="unsolicited",
        )
    )
    blob_storage = _BlobStorage()
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFilePending)
    assert result.reason is PerformanceBeatmapFilePendingReason.BEATMAP_RESOLUTION_PENDING
    assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
    assert result.mirror_reason == "unsolicited"
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_returns_unavailable_for_failed_file_fetch() -> None:
    beatmap = _make_beatmap(file_state=BeatmapFileState.FAILED)
    resolver = _Resolver(_resolve_result(beatmap, file_status=BeatmapFileState.FAILED))
    blob_storage = _BlobStorage()
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileUnavailable)
    assert result.reason is PerformanceBeatmapFileUnavailableReason.OSU_FILE_FETCH_FAILED
    assert result.provenance is None
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_returns_unavailable_for_available_state_without_attachment() -> None:
    beatmap = _make_beatmap(file_state=BeatmapFileState.AVAILABLE)
    resolver = _Resolver(_resolve_result(beatmap, file_status=BeatmapFileState.AVAILABLE))
    blob_storage = _BlobStorage()
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileUnavailable)
    assert result.reason is PerformanceBeatmapFileUnavailableReason.OSU_FILE_ATTACHMENT_UNAVAILABLE
    assert result.provenance is None
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_returns_unavailable_for_attachment_from_different_beatmap() -> None:
    attachment = _make_attachment(attachment_id=7, beatmap_id=_BEATMAP_ID + 1, blob_id=42)
    resolver = _Resolver(_resolve_result(_make_beatmap(file_attachment=attachment)))
    blob_storage = _BlobStorage({42: _OSU_BYTES})
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileUnavailable)
    assert result.reason is PerformanceBeatmapFileUnavailableReason.OSU_FILE_ATTACHMENT_MISMATCH
    assert result.provenance is None
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_returns_unavailable_for_attachment_without_persistent_id() -> None:
    attachment = _make_attachment(blob_id=42)
    resolver = _Resolver(_resolve_result(_make_beatmap(file_attachment=attachment)))
    blob_storage = _BlobStorage({42: _OSU_BYTES})
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileUnavailable)
    assert result.reason is PerformanceBeatmapFileUnavailableReason.OSU_FILE_ATTACHMENT_UNAVAILABLE
    assert result.provenance is None
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_converts_blob_read_failure_to_unavailable_result() -> None:
    attachment = _make_attachment(attachment_id=7, blob_id=42)
    resolver = _Resolver(_resolve_result(_make_beatmap(file_attachment=attachment)))
    blob_storage = _BlobStorage(error=BlobContentUnavailableError("missing blob"))
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileUnavailable)
    assert result.reason is PerformanceBeatmapFileUnavailableReason.OSU_FILE_BLOB_UNAVAILABLE
    assert result.provenance is not None
    assert result.provenance.beatmap_file_attachment_id == 7
    assert result.provenance.blob_id == 42
    assert result.provenance.checksum_md5 == _CHECKSUM
    assert blob_storage.calls == [42]


@pytest.mark.asyncio
async def test_provider_returns_unavailable_for_empty_osu_file_bytes() -> None:
    attachment = _make_attachment(attachment_id=7, blob_id=42)
    resolver = _Resolver(_resolve_result(_make_beatmap(file_attachment=attachment)))
    blob_storage = _BlobStorage({42: b""})
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileUnavailable)
    assert result.reason is PerformanceBeatmapFileUnavailableReason.OSU_FILE_EMPTY
    assert result.provenance is not None
    assert result.provenance.beatmap_file_attachment_id == 7
    assert result.provenance.blob_id == 42
    assert result.provenance.checksum_md5 == _CHECKSUM


def _make_attachment(
    *,
    blob_id: int,
    attachment_id: int | None = None,
    beatmap_id: int = _BEATMAP_ID,
) -> BeatmapFileAttachment:
    return BeatmapFileAttachment(
        beatmap_id=beatmap_id,
        blob_id=blob_id,
        checksum_md5=_CHECKSUM,
        source="mirror",
        original_filename="map.osu",
        fetched_at=_NOW,
        verified_at=_NOW,
        id=attachment_id,
    )


def _make_beatmap(
    *,
    file_state: BeatmapFileState | None = None,
    file_attachment: BeatmapFileAttachment | None = None,
) -> Beatmap:
    return Beatmap(
        id=_BEATMAP_ID,
        beatmapset_id=_BEATMAPSET_ID,
        checksum_md5=_CHECKSUM,
        mode="osu",
        version="Another",
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=file_state
        or (
            BeatmapFileState.AVAILABLE if file_attachment is not None else BeatmapFileState.MISSING
        ),
        file_attachment=file_attachment,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _resolve_result(
    beatmap: Beatmap | None,
    *,
    metadata_status: BeatmapFetchState = BeatmapFetchState.FRESH,
    file_status: BeatmapFileState | None = None,
    reason: str | None = None,
) -> BeatmapResolveResult:
    return BeatmapResolveResult(
        beatmap=beatmap,
        beatmapset=None,
        eligibility=None,
        metadata_status=metadata_status,
        file_status=file_status
        or (beatmap.file_state if beatmap is not None else BeatmapFileState.MISSING),
        source=BeatmapMetadataSource.OFFICIAL if beatmap is not None else None,
        verified=beatmap is not None,
        last_fetched_at=beatmap.last_fetched_at if beatmap is not None else None,
        next_refresh_at=beatmap.next_refresh_at if beatmap is not None else None,
        reason=reason,
    )
