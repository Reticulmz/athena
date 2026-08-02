"""blobのstream書込み,整合性metadata,deduplicationを提供するserviceを定義する."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.storage.blobs import (
    BlobDeduplicated,
    BlobStorageBackendKind,
    BlobStored,
    BlobStoreResult,
    NewBlob,
)
from osu_server.infrastructure.storage.errors import BlobContentMissingError

if TYPE_CHECKING:
    from osu_server.infrastructure.storage.interfaces import (
        BlobStorageBackend,
        ByteChunks,
        StagedBlobWrite,
    )
    from osu_server.repositories.interfaces.queries.blobs import BlobQueryRepository
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class BlobContentTypeError(ValueError):
    """blob書込みで有効なcontent typeが指定されない場合に送出する."""


class BlobContentUnavailableError(FileNotFoundError):
    """blob metadataまたはbackend contentを読み出せない場合に送出する."""


class BlobStorageWriteError(RuntimeError):
    """blob storageが成功したblob resultを生成できない場合に送出する."""


class BlobStorageService:
    """staged blob書込みをSHA-256 metadataとdeduplicationとともに調整する.

    Attributes:
        _blob_query_repo (BlobQueryRepository): blob metadataを読むrepository.
        _uow_factory (UnitOfWorkFactory): 新しいblob metadataを書き込むUnit of Workのfactory.
        _backend (BlobStorageBackend): contentをstagedに書込み,読み出すstorage backend.
        _storage_backend (BlobStorageBackendKind): 作成するmetadataに保存するbackend種別.
    """

    _blob_query_repo: BlobQueryRepository
    _uow_factory: UnitOfWorkFactory
    _backend: BlobStorageBackend
    _storage_backend: BlobStorageBackendKind

    def __init__(
        self,
        *,
        blob_query_repo: BlobQueryRepository,
        uow_factory: UnitOfWorkFactory,
        backend: BlobStorageBackend,
        storage_backend: BlobStorageBackendKind,
    ) -> None:
        """Blob storage操作に必要な依存を初期化する.

        Args:
            blob_query_repo (BlobQueryRepository): SHA-256またはIDでblob metadataを読むrepository.
            uow_factory (UnitOfWorkFactory): 新しいblob metadataを書き込むUnit of Workのfactory.
            backend (BlobStorageBackend): contentをstagedに書込み,読み出すstorage backend.
            storage_backend (BlobStorageBackendKind): 作成するmetadataに保存するbackend種別.

        """
        self._blob_query_repo = blob_query_repo
        self._uow_factory = uow_factory
        self._backend = backend
        self._storage_backend = storage_backend

    async def put_bytes(
        self,
        data: bytes,
        *,
        content_type: str,
    ) -> BlobStoreResult:
        """memory上のbyte payloadをstream書込み経路で保存する.

        Args:
            data (bytes): 保存するmemory上のpayload.
            content_type (str): 空白以外のMIME content type.

        Returns:
            BlobStoreResult: 新規保存または既存blobへのdeduplicationを表す結果.

        Raises:
            BlobContentTypeError: content_typeが空白だけの場合.
            BlobStorageWriteError: metadataの作成失敗をdeduplicationで解決できない場合.
            BackendWriteError: staged backendへの書込みまたはfinalizeが失敗した場合.
        """

        async def chunks() -> ByteChunks:
            """memory上のpayloadを一つのstream chunkとして生成する.

            Yields:
                bytes: storage backendへ渡すpayload全体.
            """
            yield data

        return await self.put_stream(chunks(), content_type=content_type)

    async def put_stream(
        self,
        chunks: ByteChunks,
        *,
        content_type: str,
    ) -> BlobStoreResult:
        """順序付きbyte streamを保存するか,既存の同一blobを返す.

        Args:
            chunks (ByteChunks): 順番に消費して保存するbyte chunk stream.
            content_type (str): 空白以外のMIME content type.

        Returns:
            BlobStoreResult: 新規保存または既存blobへのdeduplicationを表す結果.

        Raises:
            BlobContentTypeError: content_typeが空白だけの場合.
            BlobStorageWriteError: metadataの作成失敗をdeduplicationで解決できない場合.
            BackendWriteError: staged backendへの書込みまたはfinalizeが失敗した場合.

        Notes:
            SHA-256,byte size,storage keyをstream消費中に計算する. metadataはcontent
            finalize後に作成する.
        """
        normalized_content_type = _require_content_type(content_type)
        staged = None
        digest_builder = hashlib.sha256()
        byte_size = 0
        digest: str | None = None
        storage_key: str | None = None
        finalized = False

        try:
            staged = await self._backend.begin_write()
            async for chunk in chunks:
                digest_builder.update(chunk)
                byte_size += len(chunk)
                await staged.write(chunk)

            digest = digest_builder.hexdigest()
            storage_key = _storage_key_for_sha256(digest)
            existing = await self._blob_query_repo.get_by_sha256(digest)
            if existing is not None:
                await staged.discard()
                logger.debug(
                    "blob_write_deduplicated",
                    sha256=digest,
                    byte_size=byte_size,
                    blob_id=existing.id,
                    storage_backend=existing.storage_backend,
                    storage_key=existing.storage_key,
                )
                return BlobDeduplicated(existing)

            await staged.finalize(storage_key)
            finalized = True
            try:
                async with self._uow_factory() as uow:
                    created = await uow.blobs.create(
                        NewBlob(
                            sha256=digest,
                            byte_size=byte_size,
                            content_type=normalized_content_type,
                            storage_backend=self._storage_backend,
                            storage_key=storage_key,
                        )
                    )
                    await uow.commit()
            except ValueError:
                duplicate = await self._blob_query_repo.get_by_sha256(digest)
                if duplicate is not None:
                    logger.debug(
                        "blob_write_deduplicated",
                        sha256=digest,
                        byte_size=byte_size,
                        blob_id=duplicate.id,
                        storage_backend=duplicate.storage_backend,
                        storage_key=duplicate.storage_key,
                    )
                    return BlobDeduplicated(duplicate)
                raise BlobStorageWriteError(
                    f"duplicate blob disappeared before resolution: {digest}",
                ) from None
            except Exception as exc:
                raise BlobStorageWriteError("failed to create blob metadata") from exc

            logger.debug(
                "blob_write_stored",
                sha256=created.sha256,
                byte_size=created.byte_size,
                blob_id=created.id,
                storage_backend=created.storage_backend,
                storage_key=created.storage_key,
            )
            return BlobStored(created)
        except Exception as exc:
            if staged is not None and not finalized:
                await _discard_for_failure(staged)
            logger.warning(
                "blob_write_failed",
                sha256=digest,
                byte_size=byte_size,
                storage_backend=self._storage_backend,
                storage_key=storage_key,
                reason=type(exc).__name__,
            )
            raise

    async def stream_read(self, blob_id: int) -> ByteChunks:
        """既存blob metadataに対応するbackend chunk streamを開く.

        Args:
            blob_id (int): 読み出すblob metadataのID.

        Returns:
            ByteChunks: backendから順番にcontentを読むchunk stream.

        Raises:
            BlobContentUnavailableError: metadataがないか,streamを開く前にbackend
                contentがない場合.
            BlobContentMissingError: streamを返した後にbackend contentが削除された場合.
            BackendReadError: 開いたbackend streamの読取り中にerrorが発生した場合.
        """
        blob = await self._blob_query_repo.get_by_id(blob_id)
        if blob is None:
            logger.warning("blob_read_failed", blob_id=blob_id, reason="BlobMetadataMissing")
            raise BlobContentUnavailableError(f"blob content is unavailable: {blob_id}")

        try:
            return await self._backend.open_read(blob.storage_key)
        except BlobContentMissingError as exc:
            logger.warning(
                "blob_read_failed",
                blob_id=blob.id,
                storage_backend=blob.storage_backend,
                storage_key=blob.storage_key,
                reason=type(exc).__name__,
            )
            raise BlobContentUnavailableError(
                f"blob content is unavailable: {blob_id}",
            ) from exc

    async def read_bytes(self, blob_id: int) -> bytes:
        """既知の小さいblob bodyをmemoryへ読み込む.

        Args:
            blob_id (int): 読み出すblob metadataのID.

        Returns:
            bytes: streamの全chunkを連結したblob content.

        Raises:
            BlobContentUnavailableError: metadataがないか,streamを開く前にbackend
                contentがない場合.
            BlobContentMissingError: streamを返した後にbackend contentが削除された場合.
            BackendReadError: backend streamの読取り中にerrorが発生した場合.

        Notes:
            大きいblobにはstream_read()を使い,全contentをmemoryへ保持しないこと.
        """
        chunks = await self.stream_read(blob_id)
        return b"".join([chunk async for chunk in chunks])


def _require_content_type(content_type: str) -> str:
    """Content typeから前後空白を除去し,空文字列を拒否する.

    Args:
        content_type (str): callerが指定したMIME content type.

    Returns:
        str: 前後空白を除去したcontent type.

    Raises:
        BlobContentTypeError: content_typeが空白だけの場合.
    """
    normalized = content_type.strip()
    if not normalized:
        raise BlobContentTypeError("content_type must not be empty")
    return normalized


def _storage_key_for_sha256(digest: str) -> str:
    """SHA-256 digestからcontent-addressed storage keyを作成する.

    Args:
        digest (str): 16進数SHA-256 digest.

    Returns:
        str: digestの先頭4文字で分割したstorage key.
    """
    return f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"


async def _discard_for_failure(staged: StagedBlobWrite) -> None:
    """未finalizeのstaged writeを破棄し,破棄失敗を記録する.

    Args:
        staged (StagedBlobWrite): failure後に破棄するstaged backend write.

    Returns:
        None: 破棄を試行し,呼び出し側へ値を返さずに完了する.

    Notes:
        discard()の例外は元の書込み失敗を隠さないためlogへ記録して抑制する.
    """
    try:
        await staged.discard()
    except Exception as exc:
        logger.warning(
            "blob_staging_discard_failed",
            reason=type(exc).__name__,
        )


__all__ = [
    "BlobContentTypeError",
    "BlobContentUnavailableError",
    "BlobDeduplicated",
    "BlobStorageService",
    "BlobStorageWriteError",
    "BlobStoreResult",
    "BlobStored",
]
