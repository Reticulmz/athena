"""In-memory query-side blob repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.storage.blobs import Blob
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryBlobQueryRepository:
    """Read-only blob repository that reads committed memory state."""

    _factory: InMemoryUnitOfWorkFactory

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory = uow_factory

    async def get_by_id(self, blob_id: int) -> Blob | None:
        state = self._factory.snapshot()
        return state.blobs_by_id.get(blob_id)

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        state = self._factory.snapshot()
        blob_id = state.blob_id_by_sha256.get(sha256)
        if blob_id is None:
            return None
        return state.blobs_by_id.get(blob_id)
