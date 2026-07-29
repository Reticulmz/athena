"""production設定のlocal default安全性policyを検証する."""

from __future__ import annotations

import pytest

from athena_cli.env.production import ProductionSafetyError, assert_production_safe
from osu_server.config import AppConfig


def make_config(**overrides: object) -> AppConfig:
    """安全なproduction AppConfigを作り必要なfieldだけを上書きする.

    Args:
        overrides (object): 既定のproduction設定へ適用するfield値の上書き.

    Returns:
        AppConfig: validation済みのproduction向け設定.
    """
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
    """外部serviceを指す完全なproduction設定が安全判定を通ることを検証する.

    Returns:
        None: 例外を送出せずに完了する. 呼び出し側へ値を返さない.
    """
    assert_production_safe(make_config())


def test_non_production_config_is_not_checked() -> None:
    """development設定にはproduction local-default検査を適用しないことを検証する.

    Returns:
        None: 例外を送出せずに完了する. 呼び出し側へ値を返さない.
    """
    config = make_config(
        environment="development",
        database_url="postgresql+asyncpg://user:pass@localhost/athena",
        valkey_url="redis://localhost:6379/0",
        domain="athena.localhost",
        blob_storage_backend="local",
    )

    assert_production_safe(config)


def test_unsafe_local_defaults_raise_structured_error() -> None:
    """production設定に残るlocal defaultが設定名付き例外になることを検証する.

    Returns:
        None: unsafe_settingsの定義順を検証して完了する. 呼び出し側へ値を返さない.
    """
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
