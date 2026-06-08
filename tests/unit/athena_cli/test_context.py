from __future__ import annotations

import pytest

from athena_cli.context import EnvironmentName, UnsupportedEnvironmentError, resolve_context


def test_explicit_supported_environment_is_selected() -> None:
    context = resolve_context(
        selected_environment="test",
        process_environment={"ENVIRONMENT": "production", "EXISTING": "value"},
    )

    assert context.environment == "test"
    assert context.subprocess_environment["ENVIRONMENT"] == "test"
    assert context.subprocess_environment["EXISTING"] == "value"


def test_omitted_environment_uses_process_environment() -> None:
    context = resolve_context(
        selected_environment=None,
        process_environment={"ENVIRONMENT": "production"},
    )

    assert context.environment == "production"


def test_omitted_environment_defaults_to_development() -> None:
    context = resolve_context(selected_environment=None, process_environment={})

    assert context.environment == "development"
    assert context.subprocess_environment["ENVIRONMENT"] == "development"


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_supported_environment_names(environment: EnvironmentName) -> None:
    context = resolve_context(selected_environment=environment, process_environment={})

    assert context.environment == environment


def test_unsupported_environment_fails() -> None:
    with pytest.raises(UnsupportedEnvironmentError) as error_info:
        _ = resolve_context(selected_environment="staging", process_environment={})

    assert error_info.value.environment == "staging"
