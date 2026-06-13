"""SQLAlchemy query-side blob metadata repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osu_server.repositories.sqlalchemy.models.blob import BlobModel
from osu_server.repositories.sqlalchemy.queries._shared import (
    SQLAlchemyQuerySessionFactory,
    blob_to_domain,
)

if TYPE_CHECKING:
    from osu_server.domain.storage.blobs import Blob


class SQLAlchemyBlobQueryRepository:
    """Read-only blob metadata repository backed by short SQLAlchemy sessions."""

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        self._session_factory = session_factory

    async def get_by_id(self, blob_id: int) -> Blob | None:
        async with self._session_factory() as session:
            model = await session.get(BlobModel, blob_id)
            return blob_to_domain(model) if isinstance(model, BlobModel) else None

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        async with self._session_factory() as session:
            model = (
                await session.execute(select(BlobModel).where(BlobModel.sha256 == sha256))
            ).scalar_one_or_none()
            return blob_to_domain(model) if isinstance(model, BlobModel) else None
