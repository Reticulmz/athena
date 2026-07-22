"""SQLAlchemyでblob metadataを永続化するcommand repositoryを提供する."""

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
    """Unit of Work所有sessionでblob metadataを読み書きするrepository.

    Attributes:
        _session (AsyncSession): command transactionを実行しcommitを所有しないsession.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Workから受け取ったSQLAlchemy sessionを保持する.

        Args:
            session (AsyncSession): blob metadata操作に使うsession.

        Returns:
            None: repositoryの初期化完了を示す.

        Notes:
            commitとrollbackは呼び出し側のUnit of Workが所有する.
        """
        self._session: AsyncSession = session

    async def get_by_id(self, blob_id: int) -> Blob | None:
        """識別子で保存済みblob metadataを取得する.

        Args:
            blob_id (int): 取得対象blobの永続化識別子.

        Returns:
            Blob | None: 対応するblob metadata. 存在しない場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.

        Notes:
            このmethodはUnit of Workをcommitしない.
        """
        model = await self._session.get(BlobModel, blob_id)
        return _blob_to_domain(model) if isinstance(model, BlobModel) else None

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        """SHA-256 checksumで保存済みblob metadataを取得する.

        Args:
            sha256 (str): 取得対象blobのSHA-256 checksum.

        Returns:
            Blob | None: 対応するblob metadata. 存在しない場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.

        Notes:
            checksumは保存時の文字列と完全一致で照合する.
        """
        model = (
            await self._session.execute(select(BlobModel).where(BlobModel.sha256 == sha256))
        ).scalar_one_or_none()
        return _blob_to_domain(model) if isinstance(model, BlobModel) else None

    async def create(self, blob: NewBlob) -> Blob:
        """新しいblob metadataを永続化してdomain modelへ変換する.

        Args:
            blob (NewBlob): SHA-256 checksumとstorage locatorを持つ新規metadata.

        Returns:
            Blob: flushとrefresh後の永続化済みblob metadata.

        Raises:
            DuplicateBlobError: 同じSHA-256 checksumのblobが既に存在する場合.
            SQLAlchemyError: checksum重複以外の永続化処理に失敗した場合.

        Notes:
            このmethodはUnit of Workをcommitしない.
        """
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
    """SQLAlchemy blob modelをstorage domain modelへ変換する.

    Args:
        model (BlobModel): 永続化層から読み出したblob row.

    Returns:
        Blob: storage backendをdomain enumへ復元したblob metadata.

    Raises:
        ValueError: storage_backendが既知のbackend kindでない場合.
    """
    return Blob(
        id=model.id,
        sha256=model.sha256,
        byte_size=model.byte_size,
        content_type=model.content_type,
        storage_backend=BlobStorageBackendKind(model.storage_backend),
        storage_key=model.storage_key,
        created_at=model.created_at,
    )
