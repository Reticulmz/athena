from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from osu_server.infrastructure.storage import create_blob_storage_backend
from osu_server.infrastructure.storage.errors import UnsupportedBlobStorageBackendError
from osu_server.infrastructure.storage.local import LocalBlobStorageBackend
from tests.factories.config import make_app_config

if TYPE_CHECKING:
    from pathlib import Path


def test_local_backend_selection_returns_local_storage_backend(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    config = make_app_config(
        blob_storage_backend="local",
        blob_storage_local_root=str(root),
    )

    backend = create_blob_storage_backend(config)

    assert isinstance(backend, LocalBlobStorageBackend)
    assert not root.exists()


def test_s3_backend_selection_is_recognized_but_unsupported() -> None:
    config = make_app_config(
        blob_storage_backend="s3",
        blob_storage_s3_bucket="athena-blobs",
        blob_storage_s3_region="us-east-1",
        blob_storage_s3_endpoint="https://s3.example.com",
        blob_storage_s3_access_key="access-key",
        blob_storage_s3_secret_key="secret-key",
    )

    with pytest.raises(UnsupportedBlobStorageBackendError) as exc_info:
        _ = create_blob_storage_backend(config)

    assert exc_info.value.backend == "s3"
    assert config.blob_storage_s3_bucket == "athena-blobs"
    assert config.blob_storage_s3_region == "us-east-1"
    assert config.blob_storage_s3_endpoint == "https://s3.example.com"
    assert config.blob_storage_s3_access_key == "access-key"
    assert config.blob_storage_s3_secret_key == "secret-key"
