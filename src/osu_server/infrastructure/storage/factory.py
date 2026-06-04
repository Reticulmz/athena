"""Blob storage backend selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.infrastructure.storage.errors import UnsupportedBlobStorageBackendError
from osu_server.infrastructure.storage.local import LocalBlobStorageBackend

if TYPE_CHECKING:
    from osu_server.config import AppConfig
    from osu_server.infrastructure.storage.interfaces import BlobStorageBackend


def create_blob_storage_backend(config: AppConfig) -> BlobStorageBackend:
    """Create the configured blob storage backend."""
    if config.blob_storage_backend == "local":
        return LocalBlobStorageBackend(config.blob_storage_local_root)

    raise UnsupportedBlobStorageBackendError(config.blob_storage_backend)
