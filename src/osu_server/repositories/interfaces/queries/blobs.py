"""Query-side blob metadata repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.storage.blobs import Blob


class BlobQueryRepository(Protocol):
    """Read-only blob metadata access for display and compatibility workflows."""

    async def get_by_id(self, blob_id: int) -> Blob | None:
        """Return the blob with the identifier."""
        ...

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        """Return the blob with the SHA-256 checksum."""
        ...
