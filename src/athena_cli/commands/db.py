from __future__ import annotations

import asyncio
import os
from typing import Annotated

import typer

from athena_cli.context import (
    EnvironmentName,
    resolve_context,
    selected_environment_variable,
)
from athena_cli.errors import CliUserError, SubprocessFailureError, map_cli_error
from athena_cli.presentation import format_production_banner
from athena_cli.prompts import PromptAdapter
from athena_cli.runners import ProcessRunner
from osu_server.config import load_config
from osu_server.infrastructure.database.admin import create_database_if_missing

app = typer.Typer(help="Database management commands.")


@app.callback()
def db() -> None:
    """Manage Athena databases and migrations."""


def create_prompt_adapter() -> PromptAdapter:
    return PromptAdapter()


def create_process_runner() -> ProcessRunner:
    return ProcessRunner()


@app.command(name="create")
def create_database(
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
) -> None:
    try:
        _ = _create_database(environment=environment)
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


@app.command(name="migrate")
def migrate_database(
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
) -> None:
    try:
        _migrate_database(environment=environment)
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


@app.command(name="setup")
def setup_database(
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
) -> None:
    try:
        _setup_database(environment=environment)
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


def _create_database(*, environment: str | None) -> bool:
    context = resolve_context(
        selected_environment=environment,
        process_environment=dict(os.environ),
    )
    _confirm_production_create(context.environment)
    with selected_environment_variable(context.environment):
        config = load_config()
    created = asyncio.run(create_database_if_missing(str(config.database_url)))
    if created:
        typer.echo("Database created.")
    else:
        typer.echo("Database already exists.")
    return created


def _migrate_database(*, environment: str | None) -> None:
    context = resolve_context(
        selected_environment=environment,
        process_environment=dict(os.environ),
    )
    if context.environment == "production":
        typer.echo(format_production_banner())
    result = create_process_runner().run_alembic_upgrade(
        environment=context.subprocess_environment
    )
    if result.exit_code != 0:
        raise SubprocessFailureError(command=result.argv, exit_code=result.exit_code)
    typer.echo("Database migrated.")


def _setup_database(*, environment: str | None) -> None:
    _ = _create_database(environment=environment)
    _migrate_database(environment=environment)
    typer.echo("Database setup complete.")


def _confirm_production_create(environment: EnvironmentName) -> None:
    if environment != "production":
        return
    typer.echo(format_production_banner())
    if not create_prompt_adapter().confirm(
        "Create production database if missing?",
        default=False,
    ):
        raise CliUserError("Production database creation requires explicit confirmation.")
