"""Blob metadata の command-side repository 契約."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.storage.blobs import Blob, NewBlob


class DuplicateBlobError(ValueError):
    """既存 SHA-256 digest の blob metadata を作成しようとした場合の例外.

    Attributes:
        sha256 (str): 重複を検出した blob の SHA-256 digest.
    """

    sha256: str

    def __init__(self, sha256: str) -> None:
        """重複した SHA-256 digest を保持して例外を初期化する.

        Args:
            sha256 (str): 既存 blob を識別した SHA-256 digest.
        """
        self.sha256 = sha256
        super().__init__(f"blob already exists for sha256 {sha256}")


@runtime_checkable
class BlobCommandRepository(Protocol):
    """Blob metadata の mutation と deduplication-check port.

    Notes:
        Runtime 実装は command Unit of Work から取得する。各操作は同じ Unit of Work が
        所有する transaction に参加し、この repository 自身は commit または rollback を
        実行しない.
    """

    async def get_by_id(self, blob_id: int) -> Blob | None:
        """Command-side consistency check 用に identifier から Blob を返す.

        Args:
            blob_id (int): 取得する Blob ID.

        Returns:
            Blob | None: 一致する Blob。存在しない場合は None.
        """
        ...

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        """Deduplication check 用に SHA-256 digest から Blob を返す.

        Args:
            sha256 (str): 検索する content の SHA-256 digest.

        Returns:
            Blob | None: 一致する Blob。存在しない場合は None.
        """
        ...

    async def create(self, blob: NewBlob) -> Blob:
        """新しい Blob metadata を永続化する.

        Args:
            blob (NewBlob): 永続化する未保存 Blob metadata.

        Returns:
            Blob: Repository-assigned identity を含む永続化後の Blob.

        Raises:
            DuplicateBlobError: 同じ SHA-256 digest の Blob が既に存在する場合に送出する.
        """
        ...


__all__ = ["BlobCommandRepository", "DuplicateBlobError"]
