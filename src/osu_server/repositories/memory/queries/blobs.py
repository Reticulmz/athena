"""Committed in-memory state から Blob を読む query adapter を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.storage.blobs import Blob
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryBlobQueryRepository:
    """Committed in-memory state を読む read-only Blob repository.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): query ごとの committed snapshot を生成する factory.

    Notes:
        各 query は snapshot だけを読み, Blob state を変更しない.
    """

    _factory: InMemoryUnitOfWorkFactory

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Committed snapshot を取得する factory を保持する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): read に使用する committed state factory.
        """
        self._factory = uow_factory

    async def get_by_id(self, blob_id: int) -> Blob | None:
        """ID で Blob を取得する.

        Args:
            blob_id (int): 取得する Blob の ID.

        Returns:
            Blob | None: snapshot 内の Blob. ID がなければ None.
        """
        state = self._factory.snapshot()
        return state.blobs_by_id.get(blob_id)

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        """SHA-256 の索引から Blob を取得する.

        Args:
            sha256 (str): 検索する Blob の SHA-256 checksum.

        Returns:
            Blob | None: 索引先の Blob. checksum または Blob がなければ None.
        """
        state = self._factory.snapshot()
        blob_id = state.blob_id_by_sha256.get(sha256)
        if blob_id is None:
            return None
        return state.blobs_by_id.get(blob_id)
