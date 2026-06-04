"""SQLAlchemyBlobRepository — async database-backed blob metadata repository."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Protocol, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from osu_server.domain.blob import Blob
from osu_server.repositories.interfaces.blob_repository import DuplicateBlobError, NewBlob
from osu_server.repositories.sqlalchemy.models.blob import BlobModel

if TYPE_CHECKING:
    from sqlalchemy.sql.base import Executable


class _BlobResult(Protocol):
    def scalar_one_or_none(self) -> BlobModel | None: ...


class _BlobPersistenceSession(Protocol):
    def get(self, model_type: type[BlobModel], blob_id: int) -> Awaitable[BlobModel | None]: ...

    def execute(self, statement: Executable) -> Awaitable[_BlobResult]: ...

    def add(self, instance: object) -> None: ...

    def commit(self) -> Awaitable[None]: ...

    def rollback(self) -> Awaitable[None]: ...

    def refresh(self, instance: object) -> Awaitable[None]: ...


type _BlobSessionFactory = Callable[
    [],
    AbstractAsyncContextManager[object],
]


class SQLAlchemyBlobRepository:
    """SQLAlchemy implementation of the BlobRepository Protocol."""

    _session_factory: _BlobSessionFactory

    def __init__(self, session_factory: _BlobSessionFactory) -> None:
        self._session_factory = session_factory

    async def create(self, blob: NewBlob) -> Blob:
        """Persist new blob metadata with a generated id and creation time."""
        async with self._session_factory() as raw_session:
            session = cast("_BlobPersistenceSession", raw_session)
            model = BlobModel(
                sha256=blob.sha256,
                byte_size=blob.byte_size,
                content_type=blob.content_type,
                storage_backend=blob.storage_backend,
                storage_key=blob.storage_key,
            )
            session.add(model)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateBlobError(blob.sha256) from exc
            await session.refresh(model)
            return self._to_domain(model)

    async def get_by_id(self, blob_id: int) -> Blob | None:
        """Return the blob with *blob_id*, or ``None`` if not found."""
        async with self._session_factory() as raw_session:
            session = cast("_BlobPersistenceSession", raw_session)
            model = await session.get(BlobModel, blob_id)
            return self._to_domain(model) if model is not None else None

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        """Return the blob with *sha256*, or ``None`` if not found."""
        async with self._session_factory() as raw_session:
            session = cast("_BlobPersistenceSession", raw_session)
            stmt = select(BlobModel).where(BlobModel.sha256 == sha256)
            model = (await session.execute(stmt)).scalar_one_or_none()
            return self._to_domain(model) if model is not None else None

    @staticmethod
    def _to_domain(model: BlobModel) -> Blob:
        return Blob(
            id=model.id,
            sha256=model.sha256,
            byte_size=model.byte_size,
            content_type=model.content_type,
            storage_backend=model.storage_backend,
            storage_key=model.storage_key,
            created_at=model.created_at,
        )
