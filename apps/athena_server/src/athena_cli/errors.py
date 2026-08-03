"""CLIで表示するerrorとexit codeのmappingを提供する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from osu_server.config import UnsupportedEnvironmentError

if TYPE_CHECKING:
    from collections.abc import Sequence


USAGE_EXIT_CODE = 2
FAILURE_EXIT_CODE = 1


@dataclass(frozen=True, slots=True)
class CliErrorResult:
    """CLIへ表示するerror messageとexit codeを表す.

    Attributes:
        message (str): stderrへ表示するuser向けerror message.
        exit_code (int): processが返す終了code.
    """

    message: str
    exit_code: int


class CliUserError(ValueError):
    """command usageまたは入力値に起因するCLI errorを表す."""


class DatabaseOperationError(RuntimeError):
    """database operationが実行できなかったことを表す."""


class SubprocessFailureError(RuntimeError):
    """外部commandがnon-zero exit codeで終了したことを表す.

    Attributes:
        command (tuple[str, ...]): 実行した外部commandとargument.
        exit_code (int): 外部commandが返した終了code.
    """

    def __init__(self, *, command: Sequence[str], exit_code: int) -> None:
        """外部commandの失敗情報を保持して例外を初期化する.

        Args:
            command (Sequence[str]): 実行した外部commandとargument.
            exit_code (int): 外部commandが返したnon-zero終了code.
        """
        self.command: tuple[str, ...] = tuple(command)
        self.exit_code: int
        self.exit_code = exit_code
        command_text = " ".join(self.command)
        super().__init__(f"Command failed with exit code {exit_code}: {command_text}")


def map_cli_error(error: Exception) -> CliErrorResult:
    """exceptionをCLI表示用messageとexit codeへ変換する.

    Args:
        error (Exception): command実行中に捕捉したexception.

    Returns:
        CliErrorResult: exception種別に対応する表示messageと終了code.
    """
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
    """Pydantic validation errorから不正なfield名を安定順で整形する.

    Args:
        error (ValidationError): field locationを含むPydantic validation error.

    Returns:
        str: dot区切りfield名をcomma区切りで並べた表示用文字列.
    """
    field_names = {
        ".".join(str(part) for part in validation_error["loc"])
        for validation_error in error.errors()
    }
    return ", ".join(sorted(field_names))
