"""database作成とmigrationを実行するCLI command groupを定義する."""

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
    """Athena databaseとmigrationを管理するcommand groupを登録する.

    Returns:
        None: command groupのmetadataを登録し値を返さずに完了する.
    """


def create_prompt_adapter() -> PromptAdapter:
    """Production database作成確認に使うprompt adapterを生成する.

    Returns:
        PromptAdapter: default providerを持つprompt adapter.
    """
    return PromptAdapter()


def create_process_runner() -> ProcessRunner:
    """Migration commandを実行するprocess runnerを生成する.

    Returns:
        ProcessRunner: default executorを持つprocess runner.
    """
    return ProcessRunner()


def run_setup_database(*, environment: str | None) -> None:
    """database作成とmigrationを順に実行する再利用用entry pointを提供する.

    Args:
        environment (str | None): target environment. 未指定時はprocess環境を使用する.

    Returns:
        None: database setupを完了し値を返さずに完了する.

    Raises:
        CliUserError: production database作成の確認が得られない場合.
        SubprocessFailureError: alembic migrationがnon-zeroで終了した場合.
        UnsupportedEnvironmentError: environmentがsupport対象外の場合.
    """
    _setup_database(environment=environment)


@app.command(name="create", help="")
def create_database(
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
) -> None:
    """Target environmentのdatabaseがなければ作成する.

    Args:
        environment (str | None):
            database作成に使うtarget environment. 未指定時はprocess環境を使用する.

    Returns:
        None: 作成結果をCLIへ表示し値を返さずに完了する.

    Raises:
        typer.Exit: database作成またはproduction確認が失敗した場合.
    """
    try:
        _ = _create_database(environment=environment)
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


@app.command(name="migrate", help="")
def migrate_database(
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
) -> None:
    """Target environmentにalembic migrationを適用する.

    Args:
        environment (str | None):
            migrationに使うtarget environment. 未指定時はprocess環境を使用する.

    Returns:
        None: migration結果をCLIへ表示し値を返さずに完了する.

    Raises:
        typer.Exit: alembic commandまたはenvironment validationが失敗した場合.
    """
    try:
        _migrate_database(environment=environment)
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


@app.command(name="setup", help="")
def setup_database(
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
) -> None:
    """database作成後にalembic migrationを適用する.

    Args:
        environment (str | None):
            database setupに使うtarget environment. 未指定時はprocess環境を使用する.

    Returns:
        None: database setup結果をCLIへ表示し値を返さずに完了する.

    Raises:
        typer.Exit: database作成またはmigrationが失敗した場合.
    """
    try:
        _setup_database(environment=environment)
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


def _create_database(*, environment: str | None) -> bool:
    """databaseを作成し新規作成されたかを返す.

    Args:
        environment (str | None): database設定に使うtarget environment.

    Returns:
        bool: databaseをこの呼び出しで作成した場合はTrue. 既存の場合はFalse.

    Raises:
        CliUserError: production database作成の明示確認が得られない場合.
        UnsupportedEnvironmentError: environmentがsupport対象外の場合.
    """
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
    """Target environmentでalembic upgrade headを実行する.

    Args:
        environment (str | None): migrationに使うtarget environment.

    Returns:
        None: migration完了messageを表示し値を返さずに完了する.

    Raises:
        SubprocessFailureError: alembic commandがnon-zero終了codeを返した場合.
        UnsupportedEnvironmentError: environmentがsupport対象外の場合.
    """
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
    """database作成とmigrationを順に実行して完了messageを表示する.

    Args:
        environment (str | None): database setupに使うtarget environment.

    Returns:
        None: database setupを完了し値を返さずに完了する.

    Raises:
        CliUserError: production database作成の明示確認が得られない場合.
        SubprocessFailureError: alembic migrationがnon-zero終了codeを返した場合.
        UnsupportedEnvironmentError: environmentがsupport対象外の場合.
    """
    _ = _create_database(environment=environment)
    _migrate_database(environment=environment)
    typer.echo("Database setup complete.")


def _confirm_production_create(environment: EnvironmentName) -> None:
    """Production database作成に必要なuser confirmationを要求する.

    Args:
        environment (EnvironmentName): 作成対象のvalidation済みenvironment名.

    Returns:
        None: production以外または確認済みの場合に値を返さずに完了する.

    Raises:
        CliUserError: production作成への明示確認が得られない場合.
    """
    if environment != "production":
        return
    typer.echo(format_production_banner())
    if not create_prompt_adapter().confirm(
        "Create production database if missing?",
        default=False,
    ):
        raise CliUserError("Production database creation requires explicit confirmation.")
