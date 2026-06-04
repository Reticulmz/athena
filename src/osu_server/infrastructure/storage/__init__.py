"""Blob storage backend contracts and errors."""

from osu_server.infrastructure.storage.errors import (
    BackendReadError,
    BackendWriteError,
    BlobContentMissingError,
    BlobStorageConfigurationError,
    UnsupportedBlobStorageBackendError,
)
from osu_server.infrastructure.storage.interfaces import (
    BlobStorageBackend,
    ByteChunks,
    StagedBlobWrite,
)

__all__ = [
    "BackendReadError",
    "BackendWriteError",
    "BlobContentMissingError",
    "BlobStorageBackend",
    "BlobStorageConfigurationError",
    "ByteChunks",
    "StagedBlobWrite",
    "UnsupportedBlobStorageBackendError",
]
