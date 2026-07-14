from __future__ import annotations

from typing import TYPE_CHECKING

from tests.factories.beatmap import (
    make_beatmap_file_body,
    store_beatmap_file_body_blob,
)

from osu_server.domain.storage.blobs import BlobStorageBackendKind
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.blobs import InMemoryBlobQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.storage.blob_storage import BlobStorageService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from osu_server.infrastructure.storage.interfaces import ByteChunks, StagedBlobWrite


class RecordingBlobBackend:
    def __init__(self) -> None:
        self.finalized_content: dict[str, bytes] = {}

    async def validate_configuration(self) -> None:
        return None

    async def begin_write(self) -> StagedBlobWrite:
        return RecordingStagedBlobWrite(self.finalized_content)

    async def open_read(self, storage_key: str) -> ByteChunks:
        async def chunks() -> AsyncIterator[bytes]:
            yield self.finalized_content[storage_key]

        return chunks()

    async def exists(self, storage_key: str) -> bool:
        return storage_key in self.finalized_content


class RecordingStagedBlobWrite:
    _finalized_content: dict[str, bytes]
    _written_chunks: list[bytes]

    def __init__(self, finalized_content: dict[str, bytes]) -> None:
        self._finalized_content = finalized_content
        self._written_chunks = []

    async def write(self, chunk: bytes) -> None:
        self._written_chunks.append(chunk)

    async def finalize(self, storage_key: str) -> None:
        self._finalized_content[storage_key] = b"".join(self._written_chunks)

    async def discard(self) -> None:
        self._written_chunks.clear()


def _make_blob_service() -> tuple[BlobStorageService, RecordingBlobBackend]:
    backend = RecordingBlobBackend()
    command_state = InMemoryCommandRepositoryState()
    uow_factory = InMemoryUnitOfWorkFactory(command_state)
    service = BlobStorageService(
        blob_query_repo=InMemoryBlobQueryRepository(uow_factory),
        uow_factory=uow_factory,
        backend=backend,
        storage_backend=BlobStorageBackendKind.LOCAL,
    )
    return service, backend


async def test_store_beatmap_file_body_uses_blob_storage_contract() -> None:
    service, backend = _make_blob_service()
    file_body = make_beatmap_file_body(
        content=b"osu file format v14\n[Metadata]\nTitle: Test\n",
        md5="90ff874e9de3a8f00b7cae9d40c9eb5d",
        original_filename="2000.osu",
    )

    result = await store_beatmap_file_body_blob(
        service,
        file_body,
        beatmap_id=2_000,
        source="mirror",
    )

    assert backend.finalized_content[result.blob.storage_key] == file_body.content
    assert result.attachment.blob_id == result.blob.id
    assert result.attachment.beatmap_id == 2_000
    assert result.attachment.checksum_md5 == file_body.md5
    assert result.attachment.source == "mirror"
    assert result.attachment.original_filename == "2000.osu"
    assert not hasattr(result.attachment, "content")
    assert not hasattr(result.attachment, "body")


async def test_store_beatmap_file_body_deduplicates_through_blob_service() -> None:
    service, _backend = _make_blob_service()
    file_body = make_beatmap_file_body(
        content=b"same body",
        md5="841a2d689ad86bd1611447453c22c6fc",
    )

    first = await store_beatmap_file_body_blob(service, file_body)
    second = await store_beatmap_file_body_blob(service, file_body)

    assert first.blob.id == second.blob.id
    assert first.attachment.blob_id == second.attachment.blob_id
