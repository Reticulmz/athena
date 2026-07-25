"""Blob storage backendの選択と非対応設定の診断契約を検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from osu_server.infrastructure.storage import create_blob_storage_backend
from osu_server.infrastructure.storage.errors import UnsupportedBlobStorageBackendError
from osu_server.infrastructure.storage.local import LocalBlobStorageBackend
from tests.factories.config import make_app_config

if TYPE_CHECKING:
    from pathlib import Path


def test_local_backend_selection_returns_local_storage_backend(tmp_path: Path) -> None:
    """Local設定から遅延初期化のLocalBlobStorageBackendを選択する契約を検証する.

    一時rootを持つlocal設定でbackend factoryを実行する.
    local backendが返りrootを事前作成しないことを確認する.

    Args:
        tmp_path (Path): backend rootに使うpytest一時directory.

    Returns:
        None: backend選択結果を検証して完了し値を返さない.
    """
    root = tmp_path / "blobs"
    config = make_app_config(
        blob_storage_backend="local",
        blob_storage_local_root=str(root),
    )

    backend = create_blob_storage_backend(config)

    assert isinstance(backend, LocalBlobStorageBackend)
    assert not root.exists()


def test_s3_backend_selection_is_recognized_but_unsupported() -> None:
    """S3設定を既知だが未対応のbackendとして拒否する契約を検証する.

    bucketとcredentialを持つS3設定でbackend factoryを実行する.
    backend名を保持するUnsupportedBlobStorageBackendErrorが送出されることを確認する.

    Returns:
        None: 非対応backendのerror情報を検証して完了し値を返さない.
    """
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


def test_s3_backend_selection_logs_diagnostic_without_secret_values() -> None:
    """非対応S3設定の診断logがcredentialを露出しない契約を検証する.

    access keyとsecret keyを持つS3設定でbackend factoryを実行する.
    unsupported eventが1件出力されcredential文字列を含まないことを確認する.

    Returns:
        None: 安全な非対応backend診断を検証して完了し値を返さない.
    """
    config = make_app_config(
        blob_storage_backend="s3",
        blob_storage_s3_bucket="athena-blobs",
        blob_storage_s3_region="us-east-1",
        blob_storage_s3_endpoint="https://s3.example.com",
        blob_storage_s3_access_key="access-key",
        blob_storage_s3_secret_key="secret-key",
    )

    with (
        capture_logs() as logs,
        pytest.raises(UnsupportedBlobStorageBackendError),
    ):
        _ = create_blob_storage_backend(config)

    events = [event for event in logs if event["event"] == "blob_storage_backend_unsupported"]
    assert len(events) == 1
    assert events[0]["backend"] == "s3"
    assert "access-key" not in repr(logs)
    assert "secret-key" not in repr(logs)
