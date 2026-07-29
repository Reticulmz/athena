"""SQLAlchemyからBlob metadataをread-onlyで取得するquery repositoryを提供する."""

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
    """短命なSQLAlchemy read sessionでBlob metadataを取得する.

    Attributes:
        _session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread sessionのfactory.
    """

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """読み取り用session factoryを保持してrepositoryを初期化する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): query用の非同期read session factory.

        Returns:
            None: 読み取り用session factoryを保持したrepository instanceを初期化する.

        Notes:
            初期化時にはsessionを生成せず,各read operationで短命なsessionを開閉する.
        """
        self._session_factory = session_factory

    async def get_by_id(self, blob_id: int) -> Blob | None:
        """Blob IDに一致するmetadataを取得する.

        Args:
            blob_id (int): 取得対象Blobの永続ID.

        Returns:
            Blob | None: domain Blob. 対象rowが存在しない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: model.storage_backendをBlobStorageBackendKindへ変換できない場合.

        Notes:
            Blob payloadやstorage backendは変更しない.
        """
        async with self._session_factory() as session:
            model = await session.get(BlobModel, blob_id)
            return blob_to_domain(model) if isinstance(model, BlobModel) else None

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        """SHA-256 checksumに一致するBlob metadataを取得する.

        Args:
            sha256 (str): 完全一致で検索するBlob checksum.

        Returns:
            Blob | None: domain Blob. 対象rowが存在しない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: model.storage_backendをBlobStorageBackendKindへ変換できない場合.

        Notes:
            checksumの正規化は行わないため,呼び出し側は永続値と同じ表記を渡す.
        """
        async with self._session_factory() as session:
            model = (
                await session.execute(select(BlobModel).where(BlobModel.sha256 == sha256))
            ).scalar_one_or_none()
            return blob_to_domain(model) if isinstance(model, BlobModel) else None
