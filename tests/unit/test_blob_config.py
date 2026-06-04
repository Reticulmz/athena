import pytest
from pydantic import ValidationError

from tests.factories.config import make_app_config


def test_blob_storage_backend_local_is_valid() -> None:
    config = make_app_config(
        blob_storage_backend="local",
        blob_storage_local_root=".data/blobs",
    )
    assert config.blob_storage_backend == "local"
    assert config.blob_storage_local_root == ".data/blobs"


def test_blob_storage_backend_s3_is_valid() -> None:
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
    with pytest.raises(ValidationError) as exc_info:
        _ = make_app_config(blob_storage_backend="azure")
    assert "blob_storage_backend" in str(exc_info.value)


def test_make_app_config_blob_storage_defaults() -> None:
    config = make_app_config()
    assert config.blob_storage_backend == "local"
    assert config.blob_storage_local_root == ".data/blobs"
