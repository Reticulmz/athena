"""Command-side blob metadata repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.storage.blobs import Blob, NewBlob


class DuplicateBlobError(ValueError):
    """Raised when creating blob metadata for an existing SHA-256 digest."""

    sha256: str

    def __init__(self, sha256: str) -> None:
        self.sha256 = sha256
        super().__init__(f"blob already exists for sha256 {sha256}")


@runtime_checkable
class BlobCommandRepository(Protocol):
    """Mutation and deduplication-check port for blob metadata."""

    async def get_by_id(self, blob_id: int) -> Blob | None:
        """Return a blob by identifier for command-side consistency checks."""
        ...

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        """Return a blob by content checksum for deduplication checks."""
        ...

    async def create(self, blob: NewBlob) -> Blob:
        """Persist new blob metadata."""
        ...


__all__ = ["BlobCommandRepository", "DuplicateBlobError"]
