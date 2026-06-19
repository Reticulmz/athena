from __future__ import annotations

import os
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from osu_server.domain.storage.blobs import NewBlob
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.interfaces.commands.blobs import DuplicateBlobError
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    eng = create_engine(_get_database_url())
    try:
        async with eng.connect() as conn:
            _ = await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await eng.dispose()
        pytest.skip(f"DATABASE_URL is set but database is unavailable: {exc}")
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(
    engine: AsyncEngine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    factory = create_session_factory(engine)
    yield factory
    try:
        async with factory() as session:
            _ = await session.execute(
                text("DELETE FROM blobs WHERE sha256 IN (:first_sha, :second_sha)"),
                {
                    "first_sha": _digest("blob repository integration one"),
                    "second_sha": _digest("blob repository integration two"),
                },
            )
            await session.commit()
    except (OSError, SQLAlchemyError):
        return


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> SQLAlchemyUnitOfWorkFactory:
    return SQLAlchemyUnitOfWorkFactory(session_factory)


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _new_blob(*, label: str = "blob repository integration one") -> NewBlob:
    digest = _digest(label)
    return NewBlob(
        sha256=digest,
        byte_size=len(label),
        content_type="text/plain",
        storage_backend="local",
        storage_key=f"{digest[:2]}/{digest[2:4]}/{digest}",
    )


async def test_sqlalchemy_blob_repository_persists_and_retrieves_blob(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    async with uow_factory() as uow:
        created = await uow.blobs.create(_new_blob())
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.blobs.get_by_id(created.id) == created
        assert await uow.blobs.get_by_sha256(created.sha256) == created


async def test_sqlalchemy_blob_repository_rejects_duplicate_sha256(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    async with uow_factory() as uow:
        created = await uow.blobs.create(_new_blob(label="blob repository integration two"))
        await uow.commit()

    with pytest.raises(DuplicateBlobError) as exc_info:
        async with uow_factory() as uow:
            _ = await uow.blobs.create(_new_blob(label="blob repository integration two"))

    assert exc_info.value.sha256 == created.sha256
    async with uow_factory() as uow:
        assert await uow.blobs.get_by_sha256(created.sha256) == created
