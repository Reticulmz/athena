"""Beatmap file inputs for score performance calculation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol, final

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapResolveOptions,
    BeatmapResolveResult,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import BeatmapFileAttachment


class _BeatmapFileResolver(Protocol):
    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult: ...


class _BlobReader(Protocol):
    async def read_bytes(self, blob_id: int) -> bytes: ...


class PerformanceBeatmapFileStatus(Enum):
    READY = "ready"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


class PerformanceBeatmapFilePendingReason(Enum):
    BEATMAP_RESOLUTION_PENDING = "beatmap_resolution_pending"
    OSU_FILE_MISSING = "osu_file_missing"
    OSU_FILE_FETCH_PENDING = "osu_file_fetch_pending"


class PerformanceBeatmapFileUnavailableReason(Enum):
    BEATMAP_METADATA_UNAVAILABLE = "beatmap_metadata_unavailable"
    OSU_FILE_ATTACHMENT_MISMATCH = "osu_file_attachment_mismatch"
    OSU_FILE_FETCH_FAILED = "osu_file_fetch_failed"
    OSU_FILE_ATTACHMENT_UNAVAILABLE = "osu_file_attachment_unavailable"
    OSU_FILE_BLOB_UNAVAILABLE = "osu_file_blob_unavailable"
    OSU_FILE_EMPTY = "osu_file_empty"


@dataclass(slots=True, frozen=True)
class PerformanceBeatmapFileQuery:
    beatmap_id: int

    def __post_init__(self) -> None:
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class PerformanceBeatmapFileProvenance:
    """Identity exposed by BeatmapFileAttachment for later calculation provenance."""

    beatmap_id: int
    beatmap_file_attachment_id: int
    blob_id: int
    checksum_md5: str

    def __post_init__(self) -> None:
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)
        if self.beatmap_file_attachment_id <= 0:
            msg = "beatmap_file_attachment_id must be positive"
            raise ValueError(msg)
        if self.blob_id <= 0:
            msg = "blob_id must be positive"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class PerformanceBeatmapFileReady:
    beatmap_id: int
    osu_file_bytes: bytes
    provenance: PerformanceBeatmapFileProvenance
    status: PerformanceBeatmapFileStatus = field(
        init=False,
        default=PerformanceBeatmapFileStatus.READY,
    )


@dataclass(slots=True, frozen=True)
class PerformanceBeatmapFilePending:
    beatmap_id: int
    reason: PerformanceBeatmapFilePendingReason
    metadata_status: BeatmapFetchState
    file_status: BeatmapFileState
    mirror_reason: str | None
    status: PerformanceBeatmapFileStatus = field(
        init=False,
        default=PerformanceBeatmapFileStatus.PENDING,
    )


@dataclass(slots=True, frozen=True)
class PerformanceBeatmapFileUnavailable:
    beatmap_id: int
    reason: PerformanceBeatmapFileUnavailableReason
    metadata_status: BeatmapFetchState
    file_status: BeatmapFileState
    mirror_reason: str | None
    provenance: PerformanceBeatmapFileProvenance | None = None
    status: PerformanceBeatmapFileStatus = field(
        init=False,
        default=PerformanceBeatmapFileStatus.UNAVAILABLE,
    )


PerformanceBeatmapFileResult = (
    PerformanceBeatmapFileReady | PerformanceBeatmapFilePending | PerformanceBeatmapFileUnavailable
)


class PerformanceBeatmapFileProvider(Protocol):
    async def provide(
        self,
        query: PerformanceBeatmapFileQuery,
    ) -> PerformanceBeatmapFileResult: ...


@final
class BeatmapMirrorPerformanceBeatmapFileProvider:
    """Resolve PP-ready beatmap file bytes through beatmap-mirror and blob storage."""

    def __init__(
        self,
        beatmap_resolver: _BeatmapFileResolver,
        blob_storage: _BlobReader,
    ) -> None:
        self._beatmap_resolver = beatmap_resolver
        self._blob_storage = blob_storage

    async def provide(
        self,
        query: PerformanceBeatmapFileQuery,
    ) -> PerformanceBeatmapFileResult:
        result = await self._beatmap_resolver.resolve_by_beatmap_id(
            query.beatmap_id,
            BeatmapResolveOptions(require_osu_file=True),
        )

        pending_or_unavailable = _result_before_blob_read(query.beatmap_id, result)
        if pending_or_unavailable is not None:
            return pending_or_unavailable

        assert result.beatmap is not None
        attachment = result.beatmap.file_attachment
        assert attachment is not None

        return await self._read_attachment(query.beatmap_id, result, attachment)

    async def _read_attachment(
        self,
        beatmap_id: int,
        result: BeatmapResolveResult,
        attachment: BeatmapFileAttachment,
    ) -> PerformanceBeatmapFileReady | PerformanceBeatmapFileUnavailable:
        provenance = _provenance_from_attachment(attachment)
        try:
            osu_file_bytes = await self._blob_storage.read_bytes(attachment.blob_id)
        except OSError:
            return _unavailable(
                beatmap_id,
                result,
                PerformanceBeatmapFileUnavailableReason.OSU_FILE_BLOB_UNAVAILABLE,
                provenance=provenance,
            )

        if len(osu_file_bytes) == 0:
            return _unavailable(
                beatmap_id,
                result,
                PerformanceBeatmapFileUnavailableReason.OSU_FILE_EMPTY,
                provenance=provenance,
            )

        return PerformanceBeatmapFileReady(
            beatmap_id=beatmap_id,
            osu_file_bytes=osu_file_bytes,
            provenance=provenance,
        )


def _result_before_blob_read(
    beatmap_id: int,
    result: BeatmapResolveResult,
) -> PerformanceBeatmapFilePending | PerformanceBeatmapFileUnavailable | None:
    if result.beatmap is None:
        return _unknown_beatmap_result(beatmap_id, result)

    pending_reason = _pending_reason_for_file_state(result.file_status)
    if pending_reason is not None:
        return _pending(beatmap_id, result, pending_reason)

    unavailable_reason = _unavailable_reason_for_file_state(result.file_status)
    if unavailable_reason is not None:
        return _unavailable(beatmap_id, result, unavailable_reason)

    attachment_reason = _unavailable_reason_for_attachment(beatmap_id, result)
    if attachment_reason is not None:
        return _unavailable(beatmap_id, result, attachment_reason)

    return None


def _unknown_beatmap_result(
    beatmap_id: int,
    result: BeatmapResolveResult,
) -> PerformanceBeatmapFilePending | PerformanceBeatmapFileUnavailable:
    if result.metadata_status is BeatmapFetchState.FAILED:
        return _unavailable(
            beatmap_id,
            result,
            PerformanceBeatmapFileUnavailableReason.BEATMAP_METADATA_UNAVAILABLE,
        )
    return _pending(
        beatmap_id,
        result,
        PerformanceBeatmapFilePendingReason.BEATMAP_RESOLUTION_PENDING,
    )


def _pending_reason_for_file_state(
    file_state: BeatmapFileState,
) -> PerformanceBeatmapFilePendingReason | None:
    return {
        BeatmapFileState.MISSING: PerformanceBeatmapFilePendingReason.OSU_FILE_MISSING,
        BeatmapFileState.PENDING_FETCH: PerformanceBeatmapFilePendingReason.OSU_FILE_FETCH_PENDING,
    }.get(file_state)


def _unavailable_reason_for_file_state(
    file_state: BeatmapFileState,
) -> PerformanceBeatmapFileUnavailableReason | None:
    if file_state is BeatmapFileState.FAILED:
        return PerformanceBeatmapFileUnavailableReason.OSU_FILE_FETCH_FAILED
    return None


def _unavailable_reason_for_attachment(
    beatmap_id: int,
    result: BeatmapResolveResult,
) -> PerformanceBeatmapFileUnavailableReason | None:
    assert result.beatmap is not None
    attachment = result.beatmap.file_attachment
    if attachment is None or attachment.id is None:
        return PerformanceBeatmapFileUnavailableReason.OSU_FILE_ATTACHMENT_UNAVAILABLE
    if attachment.beatmap_id != beatmap_id:
        return PerformanceBeatmapFileUnavailableReason.OSU_FILE_ATTACHMENT_MISMATCH
    return None


def _pending(
    beatmap_id: int,
    result: BeatmapResolveResult,
    reason: PerformanceBeatmapFilePendingReason,
) -> PerformanceBeatmapFilePending:
    return PerformanceBeatmapFilePending(
        beatmap_id=beatmap_id,
        reason=reason,
        metadata_status=result.metadata_status,
        file_status=result.file_status,
        mirror_reason=result.reason,
    )


def _unavailable(
    beatmap_id: int,
    result: BeatmapResolveResult,
    reason: PerformanceBeatmapFileUnavailableReason,
    *,
    provenance: PerformanceBeatmapFileProvenance | None = None,
) -> PerformanceBeatmapFileUnavailable:
    return PerformanceBeatmapFileUnavailable(
        beatmap_id=beatmap_id,
        reason=reason,
        metadata_status=result.metadata_status,
        file_status=result.file_status,
        mirror_reason=result.reason,
        provenance=provenance,
    )


def _provenance_from_attachment(
    attachment: BeatmapFileAttachment,
) -> PerformanceBeatmapFileProvenance:
    assert attachment.id is not None
    return PerformanceBeatmapFileProvenance(
        beatmap_id=attachment.beatmap_id,
        beatmap_file_attachment_id=attachment.id,
        blob_id=attachment.blob_id,
        checksum_md5=attachment.checksum_md5,
    )


__all__ = (
    "BeatmapMirrorPerformanceBeatmapFileProvider",
    "PerformanceBeatmapFilePending",
    "PerformanceBeatmapFilePendingReason",
    "PerformanceBeatmapFileProvenance",
    "PerformanceBeatmapFileProvider",
    "PerformanceBeatmapFileQuery",
    "PerformanceBeatmapFileReady",
    "PerformanceBeatmapFileResult",
    "PerformanceBeatmapFileStatus",
    "PerformanceBeatmapFileUnavailable",
    "PerformanceBeatmapFileUnavailableReason",
)
