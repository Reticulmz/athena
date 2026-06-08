from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from athena_cli.context import UnsupportedEnvironmentError
from athena_cli.errors import (
    CliUserError,
    DatabaseOperationError,
    SubprocessFailureError,
    map_cli_error,
)


def test_cli_user_error_maps_to_usage_exit_code() -> None:
    result = map_cli_error(UnsupportedEnvironmentError("staging"))

    assert result.exit_code == 2
    assert "Unsupported environment 'staging'" in result.message


def test_explicit_cli_user_error_maps_to_usage_exit_code() -> None:
    result = map_cli_error(CliUserError("missing required values: DATABASE_URL"))

    assert result.exit_code == 2
    assert result.message == "missing required values: DATABASE_URL"


def test_config_validation_error_lists_invalid_settings() -> None:
    class ExampleConfig(BaseModel):
        server_port: int

    with pytest.raises(ValidationError) as error_info:
        _ = ExampleConfig.model_validate({"server_port": "not-an-int"})

    result = map_cli_error(error_info.value)

    assert result.exit_code == 2
    assert result.message == "Invalid configuration: server_port"


def test_database_operation_error_maps_to_failure_exit_code() -> None:
    result = map_cli_error(DatabaseOperationError("could not connect"))

    assert result.exit_code == 1
    assert result.message == "Database operation failed: could not connect"


def test_subprocess_failure_preserves_exit_code() -> None:
    result = map_cli_error(SubprocessFailureError(command=("pytest", "tests/"), exit_code=5))

    assert result.exit_code == 5
    assert result.message == "Command failed with exit code 5: pytest tests/"
