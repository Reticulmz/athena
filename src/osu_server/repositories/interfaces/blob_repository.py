"""BlobRepository Protocol — abstract interface for blob metadata persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.blob import Blob

_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class DuplicateBlobError(ValueError):
    """Raised when creating a blob whose SHA-256 already exists."""

    sha256: str

    def __init__(self, sha256: str) -> None:
        self.sha256 = sha256
        super().__init__(f"blob already exists for sha256 {sha256}")


@dataclass(frozen=True, slots=True)
class NewBlob:
    """Blob metadata before repository-assigned identity and creation time exist."""

    sha256: str
    byte_size: int
    content_type: str
    storage_backend: str
    storage_key: str

    def __post_init__(self) -> None:
        if not self.content_type:
            raise ValueError("content_type must not be empty")
        if self.byte_size < 0:
            raise ValueError("byte_size must be non-negative")
        if not _SHA256_PATTERN.match(self.sha256):
            raise ValueError("sha256 must be a 64-character lowercase hexadecimal string")
        if not self.storage_backend:
            raise ValueError("storage_backend must not be empty")
        if not self.storage_key:
            raise ValueError("storage_key must not be empty")


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
