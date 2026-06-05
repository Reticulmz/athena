from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, override

import pytest
from structlog.testing import capture_logs

from osu_server.infrastructure.storage.errors import BackendWriteError, BlobContentMissingError
from osu_server.repositories.memory.blob_repository import InMemoryBlobRepository
from osu_server.services.blob_storage_service import (
    BlobContentTypeError,
    BlobContentUnavailableError,
    BlobDeduplicated,
    BlobStorageService,
    BlobStored,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from osu_server.domain.blob import Blob
    from osu_server.infrastructure.storage.interfaces import ByteChunks, StagedBlobWrite
    from osu_server.repositories.interfaces.blob_repository import BlobRepository, NewBlob


async def _chunks(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


def _sha256_storage_key(content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    return f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"


class RecordingBackend:
    staged_writes: list[RecordingStagedWrite]
    finalized_content: dict[str, bytes]
    fail_writes: bool
    fail_finalize: bool
    missing_reads: set[str]

    def __init__(
        self,
        *,
        fail_writes: bool = False,
        fail_finalize: bool = False,
        missing_reads: set[str] | None = None,
    ) -> None:
        self.staged_writes = []
        self.finalized_content = {}
        self.fail_writes = fail_writes
        self.fail_finalize = fail_finalize
        self.missing_reads = missing_reads or set()

    async def validate_configuration(self) -> None:
        return None

    async def begin_write(self) -> StagedBlobWrite:
        staged = RecordingStagedWrite(
            finalized_content=self.finalized_content,
            fail_writes=self.fail_writes,
            fail_finalize=self.fail_finalize,
        )
        self.staged_writes.append(staged)
        return staged

    async def open_read(self, storage_key: str) -> ByteChunks:
        if storage_key in self.missing_reads:
            raise BlobContentMissingError(storage_key)

        async def chunks() -> AsyncIterator[bytes]:
            yield self.finalized_content[storage_key]

        return chunks()

    async def exists(self, storage_key: str) -> bool:
        return storage_key in self.finalized_content


class RecordingStagedWrite:
    _finalized_content: dict[str, bytes]
    _fail_writes: bool
    _fail_finalize: bool
    chunks: list[bytes]
    discarded: bool
    finalized_key: str | None

    def __init__(
        self,
        *,
        finalized_content: dict[str, bytes],
        fail_writes: bool,
        fail_finalize: bool,
    ) -> None:
        self._finalized_content = finalized_content
        self._fail_writes = fail_writes
        self._fail_finalize = fail_finalize
        self.chunks = []
        self.discarded = False
        self.finalized_key = None

    async def write(self, chunk: bytes) -> None:
        if self._fail_writes:
            raise BackendWriteError("forced staged write failure")
        self.chunks.append(chunk)

    async def finalize(self, storage_key: str) -> None:
        if self._fail_finalize:
            raise BackendWriteError("forced finalize failure")
        self.finalized_key = storage_key
        self._finalized_content[storage_key] = b"".join(self.chunks)

    async def discard(self) -> None:
        self.discarded = True


class FailingCreateBlobRepository(InMemoryBlobRepository):
    @override
    async def create(self, blob: NewBlob) -> Blob:
        _ = blob
        raise RuntimeError("forced metadata create failure")


def _make_service(
    *,
    repo: BlobRepository | None = None,
    backend: RecordingBackend | None = None,
) -> tuple[BlobStorageService, BlobRepository, RecordingBackend]:
    selected_repo = repo or InMemoryBlobRepository()
    selected_backend = backend or RecordingBackend()
    service = BlobStorageService(
        blob_repo=selected_repo,
        backend=selected_backend,
        storage_backend="local",
    )
    return service, selected_repo, selected_backend


async def test_put_stream_stores_new_blob_with_integrity_metadata() -> None:
    service, repo, backend = _make_service()
    content = b"hello blob storage"

    result = await service.put_stream(
        _chunks(b"hello ", b"blob ", b"storage"),
        content_type="text/plain",
    )

    assert isinstance(result, BlobStored)
    assert result.blob.sha256 == hashlib.sha256(content).hexdigest()
    assert result.blob.byte_size == len(content)
    assert result.blob.content_type == "text/plain"
    assert result.blob.storage_backend == "local"
    assert result.blob.storage_key == _sha256_storage_key(content)
    assert backend.finalized_content[result.blob.storage_key] == content
    assert await repo.get_by_sha256(result.blob.sha256) == result.blob


async def test_put_stream_accepts_explicit_octet_stream_content_type() -> None:
    service, _repo, _backend = _make_service()

    result = await service.put_stream(
        _chunks(b"unknown binary"),
        content_type="application/octet-stream",
    )

    assert isinstance(result, BlobStored)
    assert result.blob.content_type == "application/octet-stream"


async def test_put_stream_returns_existing_blob_for_duplicate_content() -> None:
    service, _repo, backend = _make_service()
    content = b"duplicate content"
    stored = await service.put_stream(_chunks(content), content_type="text/plain")
    assert isinstance(stored, BlobStored)

    with capture_logs() as logs:
        duplicate = await service.put_stream(
            _chunks(b"duplicate ", b"content"),
            content_type="application/octet-stream",
        )

    assert isinstance(duplicate, BlobDeduplicated)
    assert duplicate.blob == stored.blob
    assert len(backend.staged_writes) == 2
    assert backend.staged_writes[1].discarded is True
    assert backend.staged_writes[1].finalized_key is None
    assert backend.finalized_content == {stored.blob.storage_key: content}
    events = [event for event in logs if event["event"] == "blob_write_deduplicated"]
    assert len(events) == 1
    assert events[0]["sha256"] == stored.blob.sha256
    assert events[0]["byte_size"] == len(content)


async def test_put_bytes_matches_stream_identity_for_same_content() -> None:
    service, _repo, backend = _make_service()
    content = b"same identity through helper and stream"
    streamed = await service.put_stream(
        _chunks(b"same identity ", b"through helper ", b"and stream"),
        content_type="text/plain",
    )
    assert isinstance(streamed, BlobStored)

    helper = await service.put_bytes(content, content_type="application/octet-stream")

    assert isinstance(helper, BlobDeduplicated)
    assert helper.blob == streamed.blob
    assert helper.blob.sha256 == hashlib.sha256(content).hexdigest()
    assert helper.blob.byte_size == len(content)
    assert helper.blob.content_type == "text/plain"
    assert backend.finalized_content == {streamed.blob.storage_key: content}


async def test_put_stream_rejects_missing_content_type_before_staging() -> None:
    service, _repo, backend = _make_service()

    with pytest.raises(BlobContentTypeError):
        _ = await service.put_stream(_chunks(b"content"), content_type="")

    assert backend.staged_writes == []


async def test_put_stream_discards_staging_and_logs_when_write_fails() -> None:
    backend = RecordingBackend(fail_writes=True)
    service, repo, _backend = _make_service(backend=backend)

    with (
        capture_logs() as logs,
        pytest.raises(BackendWriteError, match="forced staged write failure"),
    ):
        _ = await service.put_stream(_chunks(b"failed content"), content_type="text/plain")

    assert len(backend.staged_writes) == 1
    assert backend.staged_writes[0].discarded is True
    assert await repo.get_by_id(1) is None
    events = [event for event in logs if event["event"] == "blob_write_failed"]
    assert len(events) == 1
    assert events[0]["reason"] == "BackendWriteError"
    assert events[0]["byte_size"] == len(b"failed content")


async def test_put_stream_discards_staging_and_logs_when_finalize_fails() -> None:
    backend = RecordingBackend(fail_finalize=True)
    service, repo, _backend = _make_service(backend=backend)

    with (
        capture_logs() as logs,
        pytest.raises(BackendWriteError, match="forced finalize failure"),
    ):
        _ = await service.put_stream(_chunks(b"failed finalize"), content_type="text/plain")

    assert len(backend.staged_writes) == 1
    assert backend.staged_writes[0].discarded is True
    assert backend.finalized_content == {}
    assert await repo.get_by_id(1) is None
    events = [event for event in logs if event["event"] == "blob_write_failed"]
    assert len(events) == 1
    assert events[0]["reason"] == "BackendWriteError"


async def test_put_stream_does_not_discard_after_finalize_when_metadata_create_fails() -> None:
    repo = FailingCreateBlobRepository()
    backend = RecordingBackend()
    service, _repo, _backend = _make_service(repo=repo, backend=backend)
    content = b"metadata create failure"

    with (
        capture_logs() as logs,
        pytest.raises(RuntimeError, match="failed to create blob metadata"),
    ):
        _ = await service.put_stream(_chunks(content), content_type="text/plain")

    assert len(backend.staged_writes) == 1
    assert backend.staged_writes[0].finalized_key == _sha256_storage_key(content)
    assert backend.staged_writes[0].discarded is False
    assert backend.finalized_content == {_sha256_storage_key(content): content}
    events = [event for event in logs if event["event"] == "blob_write_failed"]
    assert len(events) == 1
    assert events[0]["reason"] == "BlobStorageWriteError"


async def test_stream_read_returns_backend_chunks_for_existing_blob() -> None:
    service, _repo, _backend = _make_service()
    stored = await service.put_bytes(b"read me", content_type="text/plain")
    assert isinstance(stored, BlobStored)

    chunks = await service.stream_read(stored.blob.id)

    assert b"".join([chunk async for chunk in chunks]) == b"read me"
    assert await service.read_bytes(stored.blob.id) == b"read me"


async def test_stream_read_reports_missing_blob_metadata_as_unavailable() -> None:
    service, _repo, _backend = _make_service()

    with pytest.raises(BlobContentUnavailableError):
        _ = await service.stream_read(404)


async def test_stream_read_reports_missing_backend_content_as_unavailable() -> None:
    backend = RecordingBackend()
    service, _repo, _backend = _make_service(backend=backend)
    stored = await service.put_bytes(b"metadata without content", content_type="text/plain")
    assert isinstance(stored, BlobStored)
    backend.missing_reads.add(stored.blob.storage_key)

    with pytest.raises(BlobContentUnavailableError):
        _ = await service.stream_read(stored.blob.id)
