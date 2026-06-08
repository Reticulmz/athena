from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from athena_cli.context import UnsupportedEnvironmentError

if TYPE_CHECKING:
    from collections.abc import Sequence


USAGE_EXIT_CODE = 2
FAILURE_EXIT_CODE = 1


@dataclass(frozen=True, slots=True)
class CliErrorResult:
    message: str
    exit_code: int


class CliUserError(ValueError):
    pass


class DatabaseOperationError(RuntimeError):
    pass


class SubprocessFailureError(RuntimeError):
    def __init__(self, *, command: Sequence[str], exit_code: int) -> None:
        self.command: tuple[str, ...] = tuple(command)
        self.exit_code: int
        self.exit_code = exit_code
        command_text = " ".join(self.command)
        super().__init__(f"Command failed with exit code {exit_code}: {command_text}")


def map_cli_error(error: Exception) -> CliErrorResult:
    if isinstance(error, UnsupportedEnvironmentError | CliUserError):
        return CliErrorResult(message=str(error), exit_code=USAGE_EXIT_CODE)
    if isinstance(error, ValidationError):
        return CliErrorResult(
            message=f"Invalid configuration: {_format_validation_fields(error)}",
            exit_code=USAGE_EXIT_CODE,
        )
    if isinstance(error, DatabaseOperationError):
        return CliErrorResult(
            message=f"Database operation failed: {error}",
            exit_code=FAILURE_EXIT_CODE,
        )
    if isinstance(error, SubprocessFailureError):
        return CliErrorResult(message=str(error), exit_code=error.exit_code)
    return CliErrorResult(message=str(error), exit_code=FAILURE_EXIT_CODE)


def _format_validation_fields(error: ValidationError) -> str:
    field_names = {
        ".".join(str(part) for part in validation_error["loc"])
        for validation_error in error.errors()
    }
    return ", ".join(sorted(field_names))
