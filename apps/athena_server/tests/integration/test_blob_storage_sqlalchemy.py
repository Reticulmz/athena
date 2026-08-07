"""SQLAlchemy blob repositoryの永続化契約を検証するintegration test.

実PostgreSQL環境でblob作成, 取得, SHA256重複拒否を確認する.
"""

from __future__ import annotations

import os
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from osu_server.domain.storage.blobs import BlobStorageBackendKind, NewBlob
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.interfaces.commands.blobs import DuplicateBlobError
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def _get_database_url() -> str:
    """Integration test用のdatabase URLを環境変数から取得する.

    Returns:
        str: SQLAlchemy engineへ渡すdatabase接続URL.

    Raises:
        pytest.skip.Exception: DATABASE_URLが設定されていない場合.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    """接続可能なSQLAlchemy async engineを提供するfixture.

    Yields:
        AsyncGenerator[AsyncEngine]: test本体で使用する接続確認済みengine.

    Raises:
        pytest.skip.Exception: DATABASE_URLが未設定か接続先databaseが利用不能な場合.

    Notes:
        fixture終了時にengineをdisposeして接続resourceを解放する.
    """
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
    """Blob rowをcleanupするsession factoryを提供するfixture.

    Args:
        engine (AsyncEngine): 接続確認済みのSQLAlchemy async engine.

    Yields:
        AsyncGenerator[async_sessionmaker[AsyncSession]]: testがUnit of Workを作成する
            session factory.

    Notes:
        cleanup時のOSErrorとSQLAlchemyErrorはtest後のresource回収を妨げないよう無視する.
    """
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
    except OSError, SQLAlchemyError:
        return


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> SQLAlchemyUnitOfWorkFactory:
    """Blob repositoryを使用するSQLAlchemy Unit of Work factoryを作成する.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): DB sessionを生成するfactory.

    Returns:
        SQLAlchemyUnitOfWorkFactory: testがblob repositoryへアクセスするfactory.
    """
    return SQLAlchemyUnitOfWorkFactory(session_factory)


def _digest(value: str) -> str:
    """Test用blob contentのSHA256 hex digestを計算する.

    Args:
        value (str): UTF-8でhash化するtext content.

    Returns:
        str: 小文字hex表現のSHA256 digest.
    """
    return sha256(value.encode()).hexdigest()


def _new_blob(*, label: str = "blob repository integration one") -> NewBlob:
    """Local backendへ保存するtest用blob metadataを作成する.

    Args:
        label (str): digest, byte size, storage keyの元になるcontent label.

    Returns:
        NewBlob: SQLAlchemy blob repositoryへ渡す新規blob metadata.
    """
    digest = _digest(label)
    return NewBlob(
        sha256=digest,
        byte_size=len(label),
        content_type="text/plain",
        storage_backend=BlobStorageBackendKind.LOCAL,
        storage_key=f"{digest[:2]}/{digest[2:4]}/{digest}",
    )


async def test_sqlalchemy_blob_repository_persists_and_retrieves_blob(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """作成したblobをIDとSHA256の両方で取得できることを検証する.

    Args:
        uow_factory (SQLAlchemyUnitOfWorkFactory): 実PostgreSQLを使うrepository factory.

    Returns:
        None: 作成結果と2種類の取得結果をassertして終了する.

    Raises:
        AssertionError: IDまたはSHA256で取得したblobが作成値と一致しない場合.
    """
    async with uow_factory() as uow:
        created = await uow.blobs.create(_new_blob())
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.blobs.get_by_id(created.id) == created
        assert await uow.blobs.get_by_sha256(created.sha256) == created


async def test_sqlalchemy_blob_repository_rejects_duplicate_sha256(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """同一SHA256のblobを重複作成できないことを検証する.

    Args:
        uow_factory (SQLAlchemyUnitOfWorkFactory): 実PostgreSQLを使うrepository factory.

    Returns:
        None: DuplicateBlobErrorと既存blobの保持をassertして終了する.

    Raises:
        AssertionError: 重複errorのdigestまたは既存blobの取得結果が期待と異なる場合.
    """
    async with uow_factory() as uow:
        created = await uow.blobs.create(_new_blob(label="blob repository integration two"))
        await uow.commit()

    with pytest.raises(DuplicateBlobError) as exc_info:
        async with uow_factory() as uow:
            _ = await uow.blobs.create(_new_blob(label="blob repository integration two"))

    assert exc_info.value.sha256 == created.sha256
    async with uow_factory() as uow:
        assert await uow.blobs.get_by_sha256(created.sha256) == created
