"""CLI environment contextの解決契約を検証する."""

from __future__ import annotations

import pytest

from athena_cli.context import EnvironmentName, UnsupportedEnvironmentError, resolve_context


def test_explicit_supported_environment_is_selected() -> None:
    """明示したsupport対象environmentがprocess値より優先されることを検証する.

    ENVIRONMENTが異なるprocess環境を前提に解決し.
    選択値とsubprocess用値の両方が明示値になることを確認する.

    Returns:
        None: environment選択結果を検証して完了する. 呼び出し側へ値を返さない.
    """
    context = resolve_context(
        selected_environment="test",
        process_environment={"ENVIRONMENT": "production", "EXISTING": "value"},
    )

    assert context.environment == "test"
    assert context.subprocess_environment["ENVIRONMENT"] == "test"
    assert context.subprocess_environment["EXISTING"] == "value"


def test_omitted_environment_uses_process_environment() -> None:
    """未指定時にprocess環境のENVIRONMENTを採用する契約を検証する.

    Returns:
        None: process由来のenvironmentを検証して完了する. 呼び出し側へ値を返さない.
    """
    context = resolve_context(
        selected_environment=None,
        process_environment={"ENVIRONMENT": "production"},
    )

    assert context.environment == "production"


def test_omitted_environment_defaults_to_development() -> None:
    """選択値とprocess値がない場合のdevelopment既定値を検証する.

    Returns:
        None: 既定environmentとsubprocess値を検証して完了する. 呼び出し側へ値を返さない.
    """
    context = resolve_context(selected_environment=None, process_environment={})

    assert context.environment == "development"
    assert context.subprocess_environment["ENVIRONMENT"] == "development"


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_supported_environment_names(environment: EnvironmentName) -> None:
    """各support対象environment名がそのまま解決されることを検証する.

    Args:
        environment (EnvironmentName): parameterizeされたsupport対象environment名.

    Returns:
        None: 解決結果を検証して完了する. 呼び出し側へ値を返さない.
    """
    context = resolve_context(selected_environment=environment, process_environment={})

    assert context.environment == environment


def test_unsupported_environment_fails() -> None:
    """support対象外のenvironmentが入力値を保持した例外になることを検証する.

    Returns:
        None: UnsupportedEnvironmentErrorの保持値を検証して完了する. 呼び出し側へ値を返さない.
    """
    with pytest.raises(UnsupportedEnvironmentError) as error_info:
        _ = resolve_context(selected_environment="staging", process_environment={})

    assert error_info.value.environment == "staging"
