"""blob storage backendとstaged writeのtransport非依存contractを定義する."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

type ByteChunks = AsyncIterator[bytes]


@runtime_checkable
class StagedBlobWrite(Protocol):
    """finalizeされるまで読み出せないbackend staged writeを表すcontract."""

    async def write(self, chunk: bytes) -> None:
        """バイト列をstaged writeへ追記する.

        Args:
            chunk (bytes): staged contentの末尾へ追加するbyte列.

        Returns:
            None: implementationがchunkの受理または永続化を完了する.
        """
        ...

    async def finalize(self, storage_key: str) -> None:
        """一時bytesを呼出側指定のstorage keyへ公開する.

        Args:
            storage_key (str): backendがfinalized contentを識別する保存key.

        Returns:
            None: implementationがstaged contentを公開済みのcontentへ遷移させる.
        """
        ...

    async def discard(self) -> None:
        """読み出し可能なcontentを公開せずにstaged bytesを破棄する.

        Returns:
            None: implementationがstaged contentを破棄済みの状態へ遷移させる.
        """
        ...


@runtime_checkable
class BlobStorageBackend(Protocol):
    """物理blob storageをbackend非依存で操作するcontract."""

    async def validate_configuration(self) -> None:
        """書き込みを受け付ける前にbackend configurationを検証する.

        Returns:
            None: implementationが利用可能なconfigurationを確認する.
        """
        ...

    async def begin_write(self) -> StagedBlobWrite:
        """Blob content用のstaged writeを開始する.

        Returns:
            StagedBlobWrite: finalizeまたはdiscardまで読み出せないstaged write.
        """
        ...

    async def open_read(self, storage_key: str) -> ByteChunks:
        """既存storage keyのcontentを返すchunk streamを開く.

        Args:
            storage_key (str): backend内のfinalized contentを識別する保存key.

        Returns:
            ByteChunks: contentを順番に返す非同期byte iterator.
        """
        ...

    async def exists(self, storage_key: str) -> bool:
        """Storage keyに対応するfinalized contentの存在を確認する.

        Args:
            storage_key (str): backend内のfinalized contentを識別する保存key.

        Returns:
            bool: implementationが読み出し可能なcontentを保持している場合は ``True``.
        """
        ...
