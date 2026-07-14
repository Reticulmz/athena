"""SQLAlchemy command-side blob metadata repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from osu_server.domain.storage.blobs import Blob, BlobStorageBackendKind, NewBlob
from osu_server.repositories.interfaces.commands.blobs import DuplicateBlobError
from osu_server.repositories.sqlalchemy.models.blob import BlobModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyBlobCommandRepository:
    """Blob command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def get_by_id(self, blob_id: int) -> Blob | None:
        model = await self._session.get(BlobModel, blob_id)
        return _blob_to_domain(model) if isinstance(model, BlobModel) else None

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        model = (
            await self._session.execute(select(BlobModel).where(BlobModel.sha256 == sha256))
        ).scalar_one_or_none()
        return _blob_to_domain(model) if isinstance(model, BlobModel) else None

    async def create(self, blob: NewBlob) -> Blob:
        model = BlobModel(
            sha256=blob.sha256,
            byte_size=blob.byte_size,
            content_type=blob.content_type,
            storage_backend=blob.storage_backend.value,
            storage_key=blob.storage_key,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise DuplicateBlobError(blob.sha256) from exc
        await self._session.refresh(model)
        return _blob_to_domain(model)


def _blob_to_domain(model: BlobModel) -> Blob:
    return Blob(
        id=model.id,
        sha256=model.sha256,
        byte_size=model.byte_size,
        content_type=model.content_type,
        storage_backend=BlobStorageBackendKind(model.storage_backend),
        storage_key=model.storage_key,
        created_at=model.created_at,
    )
