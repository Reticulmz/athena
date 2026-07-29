"""AppConfig schema由来のenvironment file生成契約を検証する."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import athena_cli.env.generation as generation_module
from athena_cli.env.generation import (
    EnvGenerationInput,
    MissingEnvValuesError,
    generate_env_content,
)
from athena_cli.env.schema import EnvFieldMetadata

_DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/athena"
_VALKEY_URL = "redis://localhost:6379/0"


def test_generate_env_content_includes_required_values_defaults_and_environment() -> None:
    """必須値とdefaultとtarget environmentを生成内容へ含めることを検証する.

    Returns:
        None: 生成内容の必須行と末尾newlineを検証して完了する. 呼び出し側へ値を返さない.
    """
    result = generate_env_content(
        EnvGenerationInput(
            environment="test",
            values={"DATABASE_URL": _DATABASE_URL, "VALKEY_URL": _VALKEY_URL},
        )
    )

    assert "DATABASE_URL=postgresql+asyncpg://user:pass@localhost/athena" in result.content
    assert "VALKEY_URL=redis://localhost:6379/0" in result.content
    assert "ENVIRONMENT=test" in result.content
    assert "SERVER_PORT=8000" in result.content
    assert "QUERY_DIAGNOSTICS_ENABLED=" not in result.content
    assert result.content.endswith("\n")


def test_optional_bool_with_default_is_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional bool fieldに実defaultがあればenvironment fileへ出力することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): schema metadataとAppConfig validationを置き換えるfixture.

    Returns:
        None: optional bool defaultの出力行を検証して完了する. 呼び出し側へ値を返さない.
    """
    metadata = (
        EnvFieldMetadata(
            field_name="feature_enabled",
            env_var="FEATURE_ENABLED",
            required=False,
            default="false",
            secret=False,
            list_like=False,
            empty_value_is_unset=True,
        ),
    )
    monkeypatch.setattr(generation_module, "get_config_env_metadata", lambda: metadata)

    def validate_app_config(values: object) -> None:
        """このcaseでAppConfig validationを通過した入力を受け取るstubを提供する.

        Args:
            values (object): generate_env_contentがvalidationへ渡す環境変数mapping.

        Returns:
            None: stubとして入力を受け取り,値を返さずに完了する.
        """
        _ = values

    monkeypatch.setattr(generation_module, "_validate_app_config", validate_app_config)

    result = generate_env_content(EnvGenerationInput(environment="test", values={}))

    assert result.content == "FEATURE_ENABLED=false\n"


def test_missing_required_values_are_listed() -> None:
    """必須environment valueの不足名が入力順で例外に現れることを検証する.

    Returns:
        None: MissingEnvValuesErrorの不足名を検証して完了する. 呼び出し側へ値を返さない.
    """
    with pytest.raises(MissingEnvValuesError) as error_info:
        _ = generate_env_content(EnvGenerationInput(environment="test", values={}))

    assert error_info.value.missing_values == ("DATABASE_URL", "VALKEY_URL")


def test_invalid_generated_content_fails_before_write() -> None:
    """AppConfigで不正な生成内容がwrite前にvalidation errorとなることを検証する.

    Returns:
        None: ValidationErrorが発生することを検証して完了する. 呼び出し側へ値を返さない.
    """
    with pytest.raises(ValidationError):
        _ = generate_env_content(
            EnvGenerationInput(
                environment="test",
                values={"DATABASE_URL": "not-a-dsn", "VALKEY_URL": _VALKEY_URL},
            )
        )


def test_secret_values_are_masked_in_summary() -> None:
    """secret環境変数がsummaryでmaskされ元値を露出しないことを検証する.

    Returns:
        None: masked summaryの表示値を検証して完了する. 呼び出し側へ値を返さない.
    """
    result = generate_env_content(
        EnvGenerationInput(
            environment="production",
            values={
                "DATABASE_URL": "postgresql+asyncpg://user:pass@db.example.com/athena",
                "VALKEY_URL": "redis://cache.example.com:6379/0",
                "BLOB_STORAGE_BACKEND": "s3",
                "BLOB_STORAGE_S3_SECRET_KEY": "secret-value",
            },
        )
    )

    assert "BLOB_STORAGE_S3_SECRET_KEY=********" in result.masked_summary
    assert "secret-value" not in result.masked_summary
