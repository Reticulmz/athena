"""BlobStorageService — stream writes, integrity metadata, and deduplication."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.blob import BlobDeduplicated, BlobStored, BlobStoreResult
from osu_server.infrastructure.storage.errors import BlobContentMissingError
from osu_server.repositories.interfaces.blob_repository import DuplicateBlobError, NewBlob

if TYPE_CHECKING:
    from osu_server.infrastructure.storage.interfaces import (
        BlobStorageBackend,
        ByteChunks,
        StagedBlobWrite,
    )
    from osu_server.repositories.interfaces.blob_repository import BlobRepository

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class BlobContentTypeError(ValueError):
    """Raised when a blob write is requested without an explicit content type."""


class BlobContentUnavailableError(FileNotFoundError):
    """Raised when blob metadata or backend content is unavailable."""


class BlobStorageWriteError(RuntimeError):
    """Raised when blob storage cannot produce a successful blob result."""


class BlobStorageService:
    """Coordinate staged blob writes with SHA-256 metadata and deduplication."""

    _blob_repo: BlobRepository
    _backend: BlobStorageBackend
    _storage_backend: str

    def __init__(
        self,
        *,
        blob_repo: BlobRepository,
        backend: BlobStorageBackend,
        storage_backend: str,
    ) -> None:
        self._blob_repo = blob_repo
        self._backend = backend
        self._storage_backend = storage_backend

    async def put_bytes(
        self,
        data: bytes,
        *,
        content_type: str,
    ) -> BlobStoreResult:
        """Store one in-memory byte payload through the stream write path."""

        async def chunks() -> ByteChunks:
            yield data

        return await self.put_stream(chunks(), content_type=content_type)

    async def put_stream(
        self,
        chunks: ByteChunks,
        *,
        content_type: str,
    ) -> BlobStoreResult:
        """Store one sequential byte stream or return an existing duplicate blob."""
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
            existing = await self._blob_repo.get_by_sha256(digest)
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
                created = await self._blob_repo.create(
                    NewBlob(
                        sha256=digest,
                        byte_size=byte_size,
                        content_type=normalized_content_type,
                        storage_backend=self._storage_backend,
                        storage_key=storage_key,
                    )
                )
            except DuplicateBlobError:
                duplicate = await self._blob_repo.get_by_sha256(digest)
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
        """Open a backend chunk stream for existing blob metadata."""
        blob = await self._blob_repo.get_by_id(blob_id)
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
        """Read a known-small blob body into memory."""
        chunks = await self.stream_read(blob_id)
        return b"".join([chunk async for chunk in chunks])


def _require_content_type(content_type: str) -> str:
    normalized = content_type.strip()
    if not normalized:
        raise BlobContentTypeError("content_type must not be empty")
    return normalized


def _storage_key_for_sha256(digest: str) -> str:
    return f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"


async def _discard_for_failure(staged: StagedBlobWrite) -> None:
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
