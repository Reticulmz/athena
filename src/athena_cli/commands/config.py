from __future__ import annotations

import os
from typing import Annotated

import typer

from athena_cli.context import resolve_context, selected_environment_variable
from athena_cli.env.production import assert_production_safe
from athena_cli.errors import map_cli_error
from osu_server.config import load_config

app = typer.Typer(help="Configuration management commands.")


@app.callback()
def config() -> None:
    """Manage and validate Athena configuration."""


@app.command(name="check")
def check_config(
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
) -> None:
    try:
        _check_config(environment=environment)
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


def _check_config(*, environment: str | None) -> None:
    context = resolve_context(
        selected_environment=environment,
        process_environment=dict(os.environ),
    )
    with selected_environment_variable(context.environment):
        app_config = load_config()
    assert_production_safe(app_config)
    typer.echo("Configuration is valid.")
