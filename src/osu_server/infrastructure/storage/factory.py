"""application configurationからblob storage backendを選択する."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from osu_server.infrastructure.storage.errors import UnsupportedBlobStorageBackendError
from osu_server.infrastructure.storage.local import LocalBlobStorageBackend

if TYPE_CHECKING:
    from osu_server.config import AppConfig
    from osu_server.infrastructure.storage.interfaces import BlobStorageBackend

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


def create_blob_storage_backend(config: AppConfig) -> BlobStorageBackend:
    """configurationで選択されたblob storage backendを生成する.

    Args:
        config (AppConfig): backend種別とlocal storage rootを含むapplication configuration.

    Returns:
        BlobStorageBackend: ``local`` 指定時の ``LocalBlobStorageBackend`` instance.

    Raises:
        UnsupportedBlobStorageBackendError: ``local`` 以外のbackendが指定された場合.
    """
    if config.blob_storage_backend == "local":
        return LocalBlobStorageBackend(config.blob_storage_local_root)

    logger.warning(
        "blob_storage_backend_unsupported",
        backend=config.blob_storage_backend,
    )
    raise UnsupportedBlobStorageBackendError(config.blob_storage_backend)
