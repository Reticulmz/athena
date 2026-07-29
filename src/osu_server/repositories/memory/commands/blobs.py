"""In-memory command 側 blob metadata repository を実装する module."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from osu_server.domain.storage.blobs import Blob, NewBlob
from osu_server.repositories.interfaces.commands.blobs import DuplicateBlobError

if TYPE_CHECKING:
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryBlobCommandRepository:
    """Blob metadata の command-side primary record と SHA-256 index を管理する.

    Attributes:
        _state (InMemoryCommandRepositoryState): 所有 Unit of Work の可変 state snapshot.

    Notes:
        この repository は lock 又は thread synchronization を提供しない. 同じ state を
        複数 task 又は thread から同時に変更してはならない.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """Active Unit of Work の state snapshot を保持する.

        Args:
            state (InMemoryCommandRepositoryState): repository が直接読み書きする state.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def get_by_id(self, blob_id: int) -> Blob | None:
        """Blob ID から保存済み metadata を返す.

        Args:
            blob_id (int): 検索する blob の識別子.

        Returns:
            Blob | None: 保存済み blob metadata. 未登録なら None.
        """
        return self._state.blobs_by_id.get(blob_id)

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        """SHA-256 から保存済み blob metadata を返す.

        Args:
            sha256 (str): 検索する blob content の SHA-256 hex value.

        Returns:
            Blob | None: index と主記録が存在する blob. 未登録又は不整合時は None.
        """
        blob_id = self._state.blob_id_by_sha256.get(sha256)
        if blob_id is None:
            return None
        return self._state.blobs_by_id.get(blob_id)

    async def create(self, blob: NewBlob) -> Blob:
        """新しい blob metadata を作成し ID と created_at を割り当てる.

        Args:
            blob (NewBlob): 保存する content hash, size, content type, storage location.

        Returns:
            Blob: 採番済み ID と現在 UTC 時刻を持つ保存済み metadata.

        Raises:
            DuplicateBlobError: 同じ SHA-256 がすでに state に保存されている場合.

        Notes:
            成功時は next_blob_id, 主記録, SHA-256 index を更新する.
        """
        if blob.sha256 in self._state.blob_id_by_sha256:
            raise DuplicateBlobError(blob.sha256)

        created = Blob(
            id=self._state.next_blob_id,
            sha256=blob.sha256,
            byte_size=blob.byte_size,
            content_type=blob.content_type,
            storage_backend=blob.storage_backend,
            storage_key=blob.storage_key,
            created_at=datetime.now(UTC),
        )
        self._state.next_blob_id += 1
        self._state.blobs_by_id[created.id] = created
        self._state.blob_id_by_sha256[created.sha256] = created.id
        return created
