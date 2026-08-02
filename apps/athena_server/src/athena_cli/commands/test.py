"""database準備後にpytestを実行するCLI command implementationを提供する."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import typer

from athena_cli.commands import db as db_command
from athena_cli.context import resolve_context
from athena_cli.errors import SubprocessFailureError, map_cli_error
from athena_cli.runners import ProcessRunner

if TYPE_CHECKING:
    from collections.abc import Sequence


DEFAULT_TEST_PATHS = ("tests/",)


def setup_database(*, environment: str | None) -> None:
    """test実行前にdatabase作成とmigrationを実行する.

    Args:
        environment (str | None): database setupに使うtarget environment.

    Returns:
        None: database setupを完了し値を返さずに完了する.

    Raises:
        CliUserError: database setupのinput policyを満たさない場合.
        SubprocessFailureError: migrationがnon-zero終了codeを返した場合.
        UnsupportedEnvironmentError: environmentがsupport対象外の場合.
    """
    db_command.run_setup_database(environment=environment)


def create_process_runner() -> ProcessRunner:
    """Pytest commandを実行するprocess runnerを生成する.

    Returns:
        ProcessRunner: default executorを持つprocess runner.
    """
    return ProcessRunner()


def run_tests(*, environment: str | None, paths: Sequence[str]) -> None:
    """databaseを準備して指定pathまたは既定pathにpytestを実行する.

    Args:
        environment (str | None): setupとpytestに使うtarget environment.
        paths (Sequence[str]): pytestへ渡すtest path. 空の場合はDEFAULT_TEST_PATHSを使う.

    Returns:
        None: pytestが成功し値を返さずに完了する.

    Raises:
        typer.Exit: database setupまたはpytestが失敗した場合.
    """
    try:
        _run_tests(environment=environment, paths=paths)
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


def _run_tests(*, environment: str | None, paths: Sequence[str]) -> None:
    """database準備後にpytestを実行しnon-zero結果を例外へ変換する.

    Args:
        environment (str | None): setupとpytestに使うtarget environment.
        paths (Sequence[str]): pytestへ渡すtest path. 空の場合はDEFAULT_TEST_PATHSを使う.

    Returns:
        None: pytestが成功し値を返さずに完了する.

    Raises:
        SubprocessFailureError: pytestがnon-zero終了codeを返した場合.
        UnsupportedEnvironmentError: environmentがsupport対象外の場合.
    """
    setup_database(environment=environment)
    context = resolve_context(
        selected_environment=environment,
        process_environment=dict(os.environ),
    )
    test_paths = tuple(paths) if paths else DEFAULT_TEST_PATHS
    result = create_process_runner().run_pytest(
        paths=test_paths,
        environment=context.subprocess_environment,
    )
    if result.exit_code != 0:
        raise SubprocessFailureError(command=result.argv, exit_code=result.exit_code)
