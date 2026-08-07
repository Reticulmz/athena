"""blob storage configuration の検証契約を確認する."""

import pytest
from pydantic import ValidationError

from tests.factories.config import make_app_config


def test_blob_storage_backend_local_is_valid() -> None:
    """前提: local backend 用の root path を指定できる.

    操作: local backend の AppConfig を生成する.
    結果: backend と local root が指定値として保持される.

    Returns:
        None: local backend configuration 契約を検証する.
    """
    config = make_app_config(
        blob_storage_backend="local",
        blob_storage_local_root=".data/blobs",
    )
    assert config.blob_storage_backend == "local"
    assert config.blob_storage_local_root == ".data/blobs"


def test_blob_storage_backend_s3_is_valid() -> None:
    """前提: S3 backend 用の接続設定を指定できる.

    操作: S3 backend の AppConfig を生成する.
    結果: backend と bucket が指定値として保持される.

    Returns:
        None: S3 backend configuration 契約を検証する.
    """
    config = make_app_config(
        blob_storage_backend="s3",
        blob_storage_s3_bucket="my-bucket",
        blob_storage_s3_region="us-east-1",
        blob_storage_s3_endpoint="https://s3.example.com",
        blob_storage_s3_access_key="access",
        blob_storage_s3_secret_key="secret",
    )
    assert config.blob_storage_backend == "s3"
    assert config.blob_storage_s3_bucket == "my-bucket"


def test_blob_storage_backend_unknown_is_rejected() -> None:
    """前提: backend enum に未定義の値を渡せる.

    操作: unknown backend で AppConfig を生成する.
    結果: ValidationError が発生し対象 field を示す.

    Returns:
        None: backend validation 契約を検証する.
    """
    with pytest.raises(ValidationError) as exc_info:
        _ = make_app_config(blob_storage_backend="azure")
    assert "blob_storage_backend" in str(exc_info.value)


def test_make_app_config_blob_storage_defaults() -> None:
    """前提: blob storage 設定を省略できる.

    操作: default 引数で AppConfig を生成する.
    結果: local backend と既定 root が設定される.

    Returns:
        None: blob storage default 契約を検証する.
    """
    config = make_app_config()
    assert config.blob_storage_backend == "local"
    assert config.blob_storage_local_root == ".data/blobs"
