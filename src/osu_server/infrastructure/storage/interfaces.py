"""Blob storage backend contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

type ByteChunks = AsyncIterator[bytes]


@runtime_checkable
class StagedBlobWrite(Protocol):
    """Staged backend write that is not readable until finalized."""

    async def write(self, chunk: bytes) -> None:
        """Append one byte chunk to the staged write."""
        ...

    async def finalize(self, storage_key: str) -> None:
        """Finalize staged bytes to a caller-provided storage key."""
        ...

    async def discard(self) -> None:
        """Discard staged bytes without exposing readable content."""
        ...


@runtime_checkable
class BlobStorageBackend(Protocol):
    """Backend-neutral physical blob storage contract."""

    async def validate_configuration(self) -> None:
        """Validate backend configuration before accepting writes."""
        ...

    async def begin_write(self) -> StagedBlobWrite:
        """Start a staged write for blob content."""
        ...

    async def open_read(self, storage_key: str) -> ByteChunks:
        """Open a chunk stream for an existing backend storage key."""
        ...

    async def exists(self, storage_key: str) -> bool:
        """Return whether content exists at the backend storage key."""
        ...
