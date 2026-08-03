"""AppConfigからenvironment schema metadataを導出する契約を検証する."""

from __future__ import annotations

from athena_cli.env.schema import (
    get_config_env_metadata,
    render_config_example,
)
from osu_server.config import AppConfig


def test_schema_metadata_includes_every_app_config_field() -> None:
    """Schema metadataがAppConfigの全fieldを漏れなく含むことを検証する.

    Returns:
        None: field集合の一致を検証して完了する. 呼び出し側へ値を返さない.
    """
    metadata = get_config_env_metadata()

    assert {field.field_name for field in metadata} == set(AppConfig.model_fields)


def test_schema_metadata_classifies_required_defaults_secrets_and_lists() -> None:
    """Schema metadataが必須値とdefaultとsecretとlist policyを正しく分類することを検証する.

    Returns:
        None: 代表fieldのmetadataを検証して完了する. 呼び出し側へ値を返さない.
    """
    metadata = {field.field_name: field for field in get_config_env_metadata()}

    assert metadata["database_url"].env_var == "DATABASE_URL"
    assert metadata["database_url"].required is True
    assert metadata["database_url"].default is None
    assert metadata["server_port"].required is False
    assert metadata["server_port"].default == "8000"
    assert metadata["beatmap_official_api_client_secret"].secret is True
    assert metadata["beatmap_metadata_mirror_base_urls"].list_like is True
    assert metadata["query_diagnostics_enabled"].empty_value_is_unset is True


def test_example_output_is_derived_from_schema() -> None:
    """example出力がAppConfig schemaのfield数と代表値から導出されることを検証する.

    Returns:
        None: exampleの行とfield数を検証して完了する. 呼び出し側へ値を返さない.
    """
    example = render_config_example()

    assert "DATABASE_URL=" in example
    assert "VALKEY_URL=" in example
    assert "SERVER_PORT=8000" in example
    assert "BEATMAP_METADATA_MIRROR_BASE_URLS=" in example
    assert len(example.splitlines()) == len(AppConfig.model_fields)
