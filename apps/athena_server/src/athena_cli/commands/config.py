"""Athena設定を検査するCLI command groupを定義する."""

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
    """Athena設定を管理してvalidationするcommand groupを登録する.

    Returns:
        None: command groupのmetadataを登録し値を返さずに完了する.
    """


@app.command(name="check", help="")
def check_config(
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
) -> None:
    """Target environmentのAthena設定を読み込み安全性を検査する.

    Args:
        environment (str | None):
            設定読み込みに使うtarget environment. 未指定時はprocess環境を使用する.

    Returns:
        None: validation結果をCLIへ表示し値を返さずに完了する.

    Raises:
        typer.Exit: 設定validationまたはproduction safety検査が失敗した場合.
    """
    try:
        _check_config(environment=environment)
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


def _check_config(*, environment: str | None) -> None:
    """AppConfigを読み込みproduction safety policyを適用する.

    Args:
        environment (str | None): 設定読み込みに使うtarget environment.

    Returns:
        None: 設定が有効であるmessageを表示し値を返さずに完了する.

    Raises:
        UnsupportedEnvironmentError: environmentがsupport対象外の場合.
        ValidationError: AppConfig validationが失敗した場合.
        ProductionSafetyError: production設定に安全でないlocal defaultが残る場合.
    """
    context = resolve_context(
        selected_environment=environment,
        process_environment=dict(os.environ),
    )
    with selected_environment_variable(context.environment):
        app_config = load_config()
    assert_production_safe(app_config)
    typer.echo("Configuration is valid.")
