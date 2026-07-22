"""Blob metadata 用 read-only query repository contract を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.storage.blobs import Blob


class BlobQueryRepository(Protocol):
    """Display と compatibility workflow 用 blob metadata read を定義する.

    Notes:
        この Protocol は blob metadata だけを返す. Blob content や metadata を変更せず Command
        Unit of Work を開かず commit/rollback もしない.
    """

    async def get_by_id(self, blob_id: int) -> Blob | None:
        """Identifier に対応する Blob metadata を返す.

        Args:
            blob_id (int): 検索する Blob ID.

        Returns:
            Blob | None: 対応する Blob metadata. 見つからない場合は `None`.
        """
        ...

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        """SHA-256 checksum に対応する Blob metadata を返す.

        Args:
            sha256 (str): 検索する Blob SHA-256 checksum.

        Returns:
            Blob | None: 対応する Blob metadata. 見つからない場合は `None`.
        """
        ...
