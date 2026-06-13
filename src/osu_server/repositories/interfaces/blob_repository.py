"""BlobRepository Protocol — abstract interface for blob metadata persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from osu_server.domain.storage.blobs import NewBlob

if TYPE_CHECKING:
    from osu_server.domain.storage.blobs import Blob


class DuplicateBlobError(ValueError):
    """Raised when creating a blob whose SHA-256 already exists."""

    sha256: str

    def __init__(self, sha256: str) -> None:
        self.sha256 = sha256
        super().__init__(f"blob already exists for sha256 {sha256}")


@runtime_checkable
class BlobRepository(Protocol):
    """Protocol for append-only shared blob metadata persistence.

    Postconditions:
        - ``create()`` returns a persisted ``Blob`` with repository-assigned
          identity and creation time.
        - Duplicate SHA-256 creation raises ``DuplicateBlobError`` so callers
          can resolve races by reading the existing blob.
    """

    async def get_by_id(self, blob_id: int) -> Blob | None:
        """Return the blob with *blob_id*, or ``None`` if not found."""
        ...

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        """Return the blob with *sha256*, or ``None`` if not found."""
        ...

    async def create(self, blob: NewBlob) -> Blob:
        """Persist new blob metadata.

        Raises ``DuplicateBlobError`` if ``blob.sha256`` already exists.
        """
        ...


__all__ = ["BlobRepository", "DuplicateBlobError", "NewBlob"]
