"""In-memory command-side blob metadata repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from osu_server.domain.storage.blobs import Blob, NewBlob

if TYPE_CHECKING:
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryBlobCommandRepository:
    """Blob command repository backed by an active in-memory UoW state."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    async def get_by_id(self, blob_id: int) -> Blob | None:
        return self._state.blobs_by_id.get(blob_id)

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        blob_id = self._state.blob_id_by_sha256.get(sha256)
        if blob_id is None:
            return None
        return self._state.blobs_by_id.get(blob_id)

    async def create(self, blob: NewBlob) -> Blob:
        if blob.sha256 in self._state.blob_id_by_sha256:
            msg = f"blob already exists for sha256 {blob.sha256}"
            raise ValueError(msg)

        created = Blob(
            id=self._state.next_blob_id,
            sha256=blob.sha256,
            byte_size=blob.byte_size,
            content_type=blob.content_type,
            storage_backend=blob.storage_backend,
            storage_key=blob.storage_key,
            created_at=datetime.now(UTC),
        )
        self._state.next_blob_id += 1
        self._state.blobs_by_id[created.id] = created
        self._state.blob_id_by_sha256[created.sha256] = created.id
        return created
