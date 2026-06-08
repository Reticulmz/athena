from __future__ import annotations

import pytest

from athena_cli.env.production import ProductionSafetyError, assert_production_safe
from osu_server.config import AppConfig


def make_config(**overrides: object) -> AppConfig:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://user:pass@db.example.com/athena",
        "valkey_url": "redis://cache.example.com:6379/0",
        "environment": "production",
        "domain": "athena.example.com",
        "blob_storage_backend": "s3",
        "blob_storage_s3_bucket": "athena-prod",
        "blob_storage_s3_region": "ap-northeast-1",
        "blob_storage_s3_access_key": "access-key",
        "blob_storage_s3_secret_key": "secret-key",
    }
    values.update(overrides)
    return AppConfig.model_validate(values)


def test_safe_production_config_passes() -> None:
    assert_production_safe(make_config())


def test_non_production_config_is_not_checked() -> None:
    config = make_config(
        environment="development",
        database_url="postgresql+asyncpg://user:pass@localhost/athena",
        valkey_url="redis://localhost:6379/0",
        domain="athena.localhost",
        blob_storage_backend="local",
    )

    assert_production_safe(config)


def test_unsafe_local_defaults_raise_structured_error() -> None:
    config = make_config(
        database_url="postgresql+asyncpg://user:pass@localhost/athena",
        valkey_url="redis://127.0.0.1:6379/0",
        domain="athena.localhost",
        blob_storage_backend="local",
    )

    with pytest.raises(ProductionSafetyError) as error_info:
        assert_production_safe(config)

    assert error_info.value.unsafe_settings == (
        "DATABASE_URL",
        "VALKEY_URL",
        "DOMAIN",
        "BLOB_STORAGE_BACKEND",
    )
