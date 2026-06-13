"""InMemoryBlobRepository — dict-based blob metadata repository for testing."""

from __future__ import annotations

from datetime import UTC, datetime

from osu_server.domain.storage.blobs import Blob
from osu_server.repositories.interfaces.blob_repository import DuplicateBlobError, NewBlob


class InMemoryBlobRepository:
    """In-memory implementation of the BlobRepository Protocol.

    Not thread-safe — intended for single-threaded test environments only.
    """

    def __init__(self) -> None:
        self._blobs_by_id: dict[int, Blob] = {}
        self._id_by_sha256: dict[str, int] = {}
        self._next_id: int = 1

    async def create(self, blob: NewBlob) -> Blob:
        """Persist new blob metadata with an auto-generated id.

        Raises ``DuplicateBlobError`` if ``blob.sha256`` already exists.
        """
        if blob.sha256 in self._id_by_sha256:
            raise DuplicateBlobError(blob.sha256)

        created = Blob(
            id=self._next_id,
            sha256=blob.sha256,
            byte_size=blob.byte_size,
            content_type=blob.content_type,
            storage_backend=blob.storage_backend,
            storage_key=blob.storage_key,
            created_at=datetime.now(UTC),
        )
        self._next_id += 1
        self._blobs_by_id[created.id] = created
        self._id_by_sha256[created.sha256] = created.id
        return created

    async def get_by_id(self, blob_id: int) -> Blob | None:
        """Return the blob with *blob_id*, or ``None`` if not found."""
        return self._blobs_by_id.get(blob_id)

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        """Return the blob with *sha256*, or ``None`` if not found."""
        blob_id = self._id_by_sha256.get(sha256)
        if blob_id is None:
            return None
        return self._blobs_by_id.get(blob_id)
