"""CLI errorを表示messageとexit codeへ変換する契約を検証する."""

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
    """UnsupportedEnvironmentErrorがusage exit codeと入力messageへ変換されることを検証する.

    Returns:
        None: map結果のexit codeとmessageを検証して完了する. 呼び出し側へ値を返さない.
    """
    result = map_cli_error(UnsupportedEnvironmentError("staging"))

    assert result.exit_code == 2
    assert "Unsupported environment 'staging'" in result.message


def test_explicit_cli_user_error_maps_to_usage_exit_code() -> None:
    """明示的なCliUserErrorがusage exit codeと原messageを保つことを検証する.

    Returns:
        None: map結果のexit codeとmessageを検証して完了する. 呼び出し側へ値を返さない.
    """
    result = map_cli_error(CliUserError("missing required values: DATABASE_URL"))

    assert result.exit_code == 2
    assert result.message == "missing required values: DATABASE_URL"


def test_config_validation_error_lists_invalid_settings() -> None:
    """Pydantic validation errorが不正setting名を持つusage errorになることを検証する.

    Returns:
        None: map結果にfield名が含まれることを検証して完了する. 呼び出し側へ値を返さない.
    """

    class ExampleConfig(BaseModel):
        """不正なserver_portを生成する最小AppConfig代替modelを定義する.

        Attributes:
            server_port (int): intとしてvalidationするserver port.
        """

        server_port: int

    with pytest.raises(ValidationError) as error_info:
        _ = ExampleConfig.model_validate({"server_port": "not-an-int"})

    result = map_cli_error(error_info.value)

    assert result.exit_code == 2
    assert result.message == "Invalid configuration: server_port"


def test_database_operation_error_maps_to_failure_exit_code() -> None:
    """DatabaseOperationErrorがfailure exit codeとprefix付きmessageへ変換されることを検証する.

    Returns:
        None: map結果のexit codeとmessageを検証して完了する. 呼び出し側へ値を返さない.
    """
    result = map_cli_error(DatabaseOperationError("could not connect"))

    assert result.exit_code == 1
    assert result.message == "Database operation failed: could not connect"


def test_subprocess_failure_preserves_exit_code() -> None:
    """SubprocessFailureErrorが外部commandのexit codeを保持することを検証する.

    Returns:
        None: map結果のexit codeとcommand表示を検証して完了する. 呼び出し側へ値を返さない.
    """
    failure = SubprocessFailureError(
        command=("pytest", "apps/athena_server/tests/"),
        exit_code=5,
    )
    result = map_cli_error(failure)

    assert result.exit_code == 5
    assert result.message == "Command failed with exit code 5: pytest apps/athena_server/tests/"
