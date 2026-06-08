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
    db_command.run_setup_database(environment=environment)


def create_process_runner() -> ProcessRunner:
    return ProcessRunner()


def run_tests(*, environment: str | None, paths: Sequence[str]) -> None:
    try:
        _run_tests(environment=environment, paths=paths)
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


def _run_tests(*, environment: str | None, paths: Sequence[str]) -> None:
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
