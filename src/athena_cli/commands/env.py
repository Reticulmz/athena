"""environment fileを生成するCLI command groupを定義する."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from athena_cli.context import EnvironmentName, resolve_context
from athena_cli.env.dsn import build_database_dsn, build_valkey_dsn
from athena_cli.env.generation import EnvGenerationInput, generate_env_content
from athena_cli.env.schema import get_config_env_metadata, render_config_example
from athena_cli.env.writer import write_environment_file
from athena_cli.errors import map_cli_error
from athena_cli.presentation import format_environment_file_written, format_production_banner
from athena_cli.prompts import PromptAdapter

app = typer.Typer(help="Environment file management commands.")


@app.callback()
def env() -> None:
    """Athena environment fileを管理するcommand groupを登録する.

    Returns:
        None: command groupのmetadataを登録し値を返さずに完了する.
    """


@app.command(name="example", help="")
def example_environment() -> None:
    """AppConfig schema由来のenvironment file exampleを表示する.

    Returns:
        None: example内容をstdoutへ表示し値を返さずに完了する.
    """
    typer.echo(render_config_example())


def create_prompt_adapter() -> PromptAdapter:
    """Interactive environment初期化に使うprompt adapterを生成する.

    Returns:
        PromptAdapter: default providerを持つprompt adapter.
    """
    return PromptAdapter()


@app.command(name="init", help="")
def init_environment(
    environment: str,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing env file."),
    ] = False,
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="Generate from process environment."),
    ] = False,
) -> None:
    """interactiveまたはprocess環境から`.env.<environment>`を生成する.

    Args:
        environment (str): 作成するenvironment fileのtarget名.
        force (bool):
            既存fileのoverwriteを要求する場合はTrue.
        non_interactive (bool):
            promptを使わずprocess環境から値を収集する場合はTrue.

    Returns:
        None: 生成済みfile pathをCLIへ表示し値を返さずに完了する.

    Raises:
        typer.Exit: environment validationまたはfile生成が失敗した場合.
    """
    try:
        _init_environment(
            environment=environment,
            force=force,
            non_interactive=non_interactive,
        )
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


def _init_environment(*, environment: str, force: bool, non_interactive: bool) -> None:
    """Environment file生成の入力収集と書き込みを実行する.

    Args:
        environment (str): 作成するenvironment fileのtarget名.
        force (bool): 既存fileのoverwriteを要求する場合はTrue.
        non_interactive (bool): process環境から値を収集する場合はTrue.

    Returns:
        None: 生成済みfile pathを表示し値を返さずに完了する.

    Raises:
        CliUserError: overwrite policyまたはprompt入力validationを満たさない場合.
        MissingEnvValuesError: 必須環境変数値が不足している場合.
        ValidationError: 生成値がAppConfig validationを通過しない場合.
        OSError: target fileへ内容を書き込めない場合.
        UnsupportedEnvironmentError: environmentがsupport対象外の場合.
    """
    context = resolve_context(
        selected_environment=environment,
        process_environment=dict(os.environ),
    )
    prompt_adapter: PromptAdapter | None = None
    if non_interactive:
        values = _collect_non_interactive_values(context.subprocess_environment)
    else:
        prompt_adapter = create_prompt_adapter()
        values = _collect_interactive_values(prompt_adapter)
    production_confirmed = _confirm_production_overwrite(
        environment=context.environment,
        force=force,
        prompt_adapter=prompt_adapter,
    )
    generation_result = generate_env_content(
        EnvGenerationInput(environment=context.environment, values=values)
    )
    write_result = write_environment_file(
        root=Path(),
        environment=context.environment,
        content=generation_result.content,
        force=force,
        production_confirmed=production_confirmed,
    )
    typer.echo(format_environment_file_written(write_result.path))


def _collect_interactive_values(prompt_adapter: PromptAdapter) -> dict[str, str]:
    """選択したsectionの値をinteractive promptから収集する.

    Args:
        prompt_adapter (PromptAdapter): typed prompt入力を提供するadapter.

    Returns:
        dict[str, str]: 選択sectionに対応する環境変数名と値.

    Raises:
        CliUserError: prompt providerがexpectedな入力値を返さない場合.
    """
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
    return values


def _collect_non_interactive_values(process_environment: dict[str, str]) -> dict[str, str]:
    """process環境に存在するAppConfig用変数だけを収集する.

    Args:
        process_environment (dict[str, str]): 呼び出し元processの環境変数.

    Returns:
        dict[str, str]: schemaで定義されprocess環境にも存在する環境変数名と値.
    """
    return {
        field.env_var: process_environment[field.env_var]
        for field in get_config_env_metadata()
        if field.env_var in process_environment
    }


def _confirm_production_overwrite(
    *,
    environment: EnvironmentName,
    force: bool,
    prompt_adapter: PromptAdapter | None,
) -> bool:
    """Production fileをoverwriteするためのconfirmation状態を判定する.

    Args:
        environment (EnvironmentName): validation済みのtarget environment名.
        force (bool): overwriteを要求する場合はTrue.
        prompt_adapter (PromptAdapter | None): interactive時のconfirmation取得用adapter.

    Returns:
        bool: productionでforceとuser confirmationがそろう場合だけTrue.
    """
    if environment != "production":
        return False
    typer.echo(format_production_banner())
    if not force or prompt_adapter is None:
        return False
    return prompt_adapter.confirm(
        "Overwrite .env.production?",
        default=False,
    )
