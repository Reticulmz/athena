from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import md5
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.storage.blobs import Blob
    from osu_server.services.blob_storage_service import BlobStorageService

_DEFAULT_BEATMAP_ID = 2_000
_DEFAULT_BEATMAPSET_ID = 1_000
_DEFAULT_CHECKSUM_MD5 = "0123456789abcdef0123456789abcdef"


class FakeProviderResultKind(StrEnum):
    SUCCESS = "success"
    PENDING = "pending"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    SERVER_FAILURE = "server_failure"


class FakeProviderErrorKind(StrEnum):
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    SERVER_FAILURE = "server_failure"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    NOT_FOUND = "not_found"


@dataclass(slots=True, frozen=True)
class BeatmapSnapshotFactory:
    beatmap_id: int
    beatmapset_id: int
    checksum_md5: str
    mode: str
    version: str
    official_status: str
    official_status_source: str
    official_status_verified: bool
    local_status_override: str | None
    source: str
    verified: bool
    last_fetched_at: datetime
    next_refresh_at: datetime


@dataclass(slots=True, frozen=True)
class BeatmapSetSnapshotFactory:
    beatmapset_id: int
    artist: str
    title: str
    creator: str
    source: str
    verified: bool
    official_status: str
    official_status_source: str
    official_status_verified: bool
    beatmaps: tuple[BeatmapSnapshotFactory, ...]
    last_fetched_at: datetime
    next_refresh_at: datetime


@dataclass(slots=True, frozen=True)
class BeatmapFetchStateFactory:
    target_type: str
    target_key: str
    status: str
    attempt_count: int
    last_error: str | None
    pending_since: datetime | None
    last_attempted_at: datetime | None


@dataclass(slots=True, frozen=True)
class BeatmapFileAttachmentFactory:
    beatmap_id: int
    blob_id: int
    checksum_md5: str
    verified_md5: str
    source: str
    original_filename: str
    fetched_at: datetime
    verified_at: datetime


@dataclass(slots=True, frozen=True)
class BeatmapFileBodyFactory:
    content: bytes
    md5: str
    original_filename: str


@dataclass(slots=True, frozen=True)
class BeatmapBlobStorageWriteFactory:
    blob: Blob
    attachment: BeatmapFileAttachmentFactory


@dataclass(slots=True, frozen=True)
class FakeMetadataProviderResponse:
    kind: FakeProviderResultKind
    snapshot: BeatmapSetSnapshotFactory | None = None
    error_kind: FakeProviderErrorKind | None = None


@dataclass(slots=True, frozen=True)
class FakeFileProviderResponse:
    kind: FakeProviderResultKind
    body: BeatmapFileBodyFactory | None = None
    source: str = "official"
    error_kind: FakeProviderErrorKind | None = None


def make_beatmap_snapshot_factory(
    *,
    beatmap_id: int = _DEFAULT_BEATMAP_ID,
    beatmapset_id: int = _DEFAULT_BEATMAPSET_ID,
    checksum_md5: str = _DEFAULT_CHECKSUM_MD5,
    mode: str = "osu",
    version: str = "Another",
    official_status: str = "ranked",
    official_status_source: str = "osu_api",
    official_status_verified: bool = True,
    local_status_override: str | None = None,
    source: str = "official",
    verified: bool = True,
    last_fetched_at: datetime | None = None,
    next_refresh_at: datetime | None = None,
) -> BeatmapSnapshotFactory:
    fetched_at = last_fetched_at or datetime.now(UTC)
    return BeatmapSnapshotFactory(
        beatmap_id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=checksum_md5,
        mode=mode,
        version=version,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        local_status_override=local_status_override,
        source=source,
        verified=verified,
        last_fetched_at=fetched_at,
        next_refresh_at=next_refresh_at or fetched_at + timedelta(days=30),
    )


def make_beatmapset_snapshot_factory(
    *,
    beatmapset_id: int = _DEFAULT_BEATMAPSET_ID,
    artist: str = "Camellia",
    title: str = "Exit This Earth's Atomosphere",
    creator: str = "Realazy",
    source: str = "official",
    verified: bool = True,
    official_status: str = "ranked",
    official_status_source: str = "osu_api",
    official_status_verified: bool = True,
    beatmaps: Iterable[BeatmapSnapshotFactory] | None = None,
    last_fetched_at: datetime | None = None,
    next_refresh_at: datetime | None = None,
) -> BeatmapSetSnapshotFactory:
    fetched_at = last_fetched_at or datetime.now(UTC)
    child_beatmaps = tuple(
        beatmaps
        if beatmaps is not None
        else (
            make_beatmap_snapshot_factory(
                beatmapset_id=beatmapset_id,
                official_status=official_status,
                official_status_source=official_status_source,
                official_status_verified=official_status_verified,
                source=source,
                verified=verified,
                last_fetched_at=fetched_at,
            ),
        )
    )
    return BeatmapSetSnapshotFactory(
        beatmapset_id=beatmapset_id,
        artist=artist,
        title=title,
        creator=creator,
        source=source,
        verified=verified,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        beatmaps=child_beatmaps,
        last_fetched_at=fetched_at,
        next_refresh_at=next_refresh_at or fetched_at + timedelta(days=30),
    )


def make_beatmap_fetch_state_factory(
    *,
    target_type: str = "metadata",
    target_key: str = "2000",
    status: str = "pending",
    attempt_count: int = 0,
    last_error: str | None = None,
    pending_since: datetime | None = None,
    last_attempted_at: datetime | None = None,
) -> BeatmapFetchStateFactory:
    return BeatmapFetchStateFactory(
        target_type=target_type,
        target_key=target_key,
        status=status,
        attempt_count=attempt_count,
        last_error=last_error,
        pending_since=pending_since,
        last_attempted_at=last_attempted_at,
    )


def make_beatmap_file_attachment_factory(
    *,
    beatmap_id: int = _DEFAULT_BEATMAP_ID,
    blob_id: int = 1,
    checksum_md5: str = _DEFAULT_CHECKSUM_MD5,
    verified_md5: str | None = None,
    source: str = "official",
    original_filename: str = "2000.osu",
    fetched_at: datetime | None = None,
    verified_at: datetime | None = None,
) -> BeatmapFileAttachmentFactory:
    fetched = fetched_at or datetime.now(UTC)
    return BeatmapFileAttachmentFactory(
        beatmap_id=beatmap_id,
        blob_id=blob_id,
        checksum_md5=checksum_md5,
        verified_md5=verified_md5 or checksum_md5,
        source=source,
        original_filename=original_filename,
        fetched_at=fetched,
        verified_at=verified_at or fetched,
    )


def make_beatmap_file_body(
    *,
    content: bytes = b"osu file format v14\n[General]\nAudioFilename: audio.mp3\n",
    md5: str | None = _DEFAULT_CHECKSUM_MD5,
    original_filename: str = "2000.osu",
) -> BeatmapFileBodyFactory:
    return BeatmapFileBodyFactory(
        content=content,
        md5=md5 or _md5_hex(content),
        original_filename=original_filename,
    )


def make_metadata_provider_response(
    *,
    kind: FakeProviderResultKind = FakeProviderResultKind.SUCCESS,
    snapshot: BeatmapSetSnapshotFactory | None = None,
    error_kind: FakeProviderErrorKind | None = None,
) -> FakeMetadataProviderResponse:
    return FakeMetadataProviderResponse(
        kind=kind,
        snapshot=snapshot
        if kind is not FakeProviderResultKind.SUCCESS
        else snapshot or make_beatmapset_snapshot_factory(),
        error_kind=error_kind or _error_kind_for_result(kind),
    )


def make_file_provider_response(
    *,
    kind: FakeProviderResultKind = FakeProviderResultKind.SUCCESS,
    body: BeatmapFileBodyFactory | None = None,
    source: str = "official",
    error_kind: FakeProviderErrorKind | None = None,
) -> FakeFileProviderResponse:
    resolved_error = error_kind or _error_kind_for_result(kind)
    resolved_kind = kind if error_kind is None else _result_kind_for_error(error_kind)
    return FakeFileProviderResponse(
        kind=resolved_kind,
        body=body if resolved_kind is FakeProviderResultKind.SUCCESS else None,
        source=source,
        error_kind=resolved_error,
    )


@dataclass(slots=True)
class FakeBeatmapMetadataProvider:
    by_beatmap_id: dict[int, FakeMetadataProviderResponse] = field(default_factory=dict)
    by_beatmapset_id: dict[int, FakeMetadataProviderResponse] = field(default_factory=dict)
    by_checksum: dict[str, FakeMetadataProviderResponse] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    default_response: FakeMetadataProviderResponse = field(
        default_factory=lambda: make_metadata_provider_response(
            kind=FakeProviderResultKind.NOT_FOUND
        )
    )

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> FakeMetadataProviderResponse:
        self.calls.append(("beatmap_id", str(beatmap_id)))
        return self.by_beatmap_id.get(beatmap_id, self.default_response)

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> FakeMetadataProviderResponse:
        self.calls.append(("beatmapset_id", str(beatmapset_id)))
        return self.by_beatmapset_id.get(beatmapset_id, self.default_response)

    async def lookup_by_checksum(self, checksum_md5: str) -> FakeMetadataProviderResponse:
        self.calls.append(("checksum_md5", checksum_md5))
        return self.by_checksum.get(checksum_md5, self.default_response)


@dataclass(slots=True)
class FakeBeatmapFileProvider:
    by_beatmap_id: dict[int, FakeFileProviderResponse] = field(default_factory=dict)
    calls: list[int] = field(default_factory=list)
    default_response: FakeFileProviderResponse = field(
        default_factory=lambda: make_file_provider_response(kind=FakeProviderResultKind.NOT_FOUND)
    )

    async def fetch_osu_file(self, beatmap_id: int) -> FakeFileProviderResponse:
        self.calls.append(beatmap_id)
        return self.by_beatmap_id.get(beatmap_id, self.default_response)


async def store_beatmap_file_body_blob(
    blob_storage_service: BlobStorageService,
    file_body: BeatmapFileBodyFactory,
    *,
    beatmap_id: int = _DEFAULT_BEATMAP_ID,
    source: str = "official",
) -> BeatmapBlobStorageWriteFactory:
    result = await blob_storage_service.put_bytes(
        file_body.content,
        content_type="application/octet-stream",
    )
    blob = result.blob
    attachment = make_beatmap_file_attachment_factory(
        beatmap_id=beatmap_id,
        blob_id=blob.id,
        checksum_md5=file_body.md5,
        verified_md5=file_body.md5,
        source=source,
        original_filename=file_body.original_filename,
    )
    return BeatmapBlobStorageWriteFactory(blob=blob, attachment=attachment)


def _error_kind_for_result(kind: FakeProviderResultKind) -> FakeProviderErrorKind | None:
    if kind in {FakeProviderResultKind.SUCCESS, FakeProviderResultKind.PENDING}:
        return None
    if kind is FakeProviderResultKind.NOT_FOUND:
        return FakeProviderErrorKind.NOT_FOUND
    if kind is FakeProviderResultKind.RATE_LIMITED:
        return FakeProviderErrorKind.RATE_LIMITED
    if kind is FakeProviderResultKind.TIMEOUT:
        return FakeProviderErrorKind.TIMEOUT
    return FakeProviderErrorKind.SERVER_FAILURE


def _result_kind_for_error(error_kind: FakeProviderErrorKind) -> FakeProviderResultKind:
    if error_kind is FakeProviderErrorKind.NOT_FOUND:
        return FakeProviderResultKind.NOT_FOUND
    if error_kind is FakeProviderErrorKind.RATE_LIMITED:
        return FakeProviderResultKind.RATE_LIMITED
    if error_kind is FakeProviderErrorKind.TIMEOUT:
        return FakeProviderResultKind.TIMEOUT
    return FakeProviderResultKind.SERVER_FAILURE


def _md5_hex(content: bytes) -> str:
    return md5(content, usedforsecurity=False).hexdigest()
