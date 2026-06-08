from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from athena_cli.context import resolve_context
from athena_cli.env.dsn import build_database_dsn, build_valkey_dsn
from athena_cli.env.generation import EnvGenerationInput, generate_env_content
from athena_cli.env.writer import write_environment_file
from athena_cli.errors import map_cli_error
from athena_cli.presentation import format_environment_file_written, format_production_banner
from athena_cli.prompts import PromptAdapter

app = typer.Typer(help="Environment file management commands.")


@app.callback()
def env() -> None:
    """Manage Athena environment files."""


def create_prompt_adapter() -> PromptAdapter:
    return PromptAdapter()


@app.command(name="init")
def init_environment(
    environment: str,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing env file."),
    ] = False,
) -> None:
    try:
        _init_environment(environment=environment, force=force)
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


def _init_environment(*, environment: str, force: bool) -> None:
    context = resolve_context(
        selected_environment=environment,
        process_environment=dict(os.environ),
    )
    prompt_adapter = create_prompt_adapter()
    selected_sections = prompt_adapter.select_sections()
    values: dict[str, str] = {}
    if "database" in selected_sections:
        database_dsn = build_database_dsn(prompt_adapter.collect_database_parts())
        values["DATABASE_URL"] = database_dsn.value
    if "valkey" in selected_sections:
        valkey_dsn = build_valkey_dsn(prompt_adapter.collect_valkey_parts())
        values["VALKEY_URL"] = valkey_dsn.value
    if "osu_api" in selected_sections:
        osu_api = prompt_adapter.collect_osu_api_config()
        values["BEATMAP_OFFICIAL_SOURCES_ENABLED"] = str(osu_api.enabled).lower()
        if osu_api.client_id is not None:
            values["BEATMAP_OFFICIAL_API_CLIENT_ID"] = osu_api.client_id
        if osu_api.client_secret is not None:
            values["BEATMAP_OFFICIAL_API_CLIENT_SECRET"] = osu_api.client_secret

    generation_result = generate_env_content(
        EnvGenerationInput(environment=context.environment, values=values)
    )
    production_confirmed = False
    if context.environment == "production":
        typer.echo(format_production_banner())
        if force:
            production_confirmed = prompt_adapter.confirm(
                "Overwrite .env.production?",
                default=False,
            )
    write_result = write_environment_file(
        root=Path(),
        environment=context.environment,
        content=generation_result.content,
        force=force,
        production_confirmed=production_confirmed,
    )
    typer.echo(format_environment_file_written(write_result.path))
