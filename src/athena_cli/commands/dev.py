from __future__ import annotations

import asyncio
import os
from typing import Annotated

import typer

from athena_cli.context import resolve_context, selected_environment_variable
from athena_cli.errors import CliUserError, map_cli_error
from athena_cli.prompts import PromptAdapter
from osu_server.composition.management import (
    change_user_password as run_change_user_password,
)
from osu_server.composition.management import change_user_role as run_change_user_role
from osu_server.config import load_config
from osu_server.domain.identity.sessions import AuthorizationRefreshStatus
from osu_server.services.commands.identity import (
    ChangeUserPasswordCommandInput,
    ChangeUserPasswordCommandResult,
    ChangeUserPasswordStatus,
    ChangeUserRoleCommandInput,
    ChangeUserRoleCommandResult,
    ChangeUserRoleStatus,
)

app = typer.Typer(help="Development-only utility commands.")


@app.callback()
def dev() -> None:
    """Run development-only utilities."""


def create_prompt_adapter() -> PromptAdapter:
    return PromptAdapter()


@app.command(name="change-password")
def change_password(
    username: Annotated[
        str,
        typer.Argument(help="Username whose password should be changed."),
    ],
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
) -> None:
    try:
        _change_password(username=username, environment=environment)
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


@app.command(name="change-role")
def change_role(
    username: Annotated[
        str,
        typer.Argument(help="Username whose role should be changed."),
    ],
    role_name: Annotated[
        str,
        typer.Argument(help="Role name to assign as the user's only role."),
    ],
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
) -> None:
    try:
        _change_role(
            username=username,
            role_name=role_name,
            environment=environment,
        )
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


def _change_password(*, username: str, environment: str | None) -> None:
    context = resolve_context(
        selected_environment=environment,
        process_environment=dict(os.environ),
    )
    if context.environment == "production":
        raise CliUserError(
            "Password changes from the dev CLI are only available for development and test."
        )

    password = create_prompt_adapter().collect_confirmed_secret(
        message="New password",
        confirmation_message="Confirm new password",
    )
    with selected_environment_variable(context.environment):
        config = load_config()
    result = asyncio.run(
        run_change_user_password(
            config,
            ChangeUserPasswordCommandInput(
                username=username,
                plain_password=password,
            ),
        )
    )
    _report_password_result(result)


def _change_role(*, username: str, role_name: str, environment: str | None) -> None:
    context = resolve_context(
        selected_environment=environment,
        process_environment=dict(os.environ),
    )
    if context.environment == "production":
        raise CliUserError(
            "Role changes from the dev CLI are only available for development and test."
        )

    with selected_environment_variable(context.environment):
        config = load_config()
    result = asyncio.run(
        run_change_user_role(
            config,
            ChangeUserRoleCommandInput(
                username=username,
                role_name=role_name,
            ),
        )
    )
    _report_role_result(result)


def _report_password_result(result: ChangeUserPasswordCommandResult) -> None:
    if result.status is ChangeUserPasswordStatus.CHANGED:
        typer.echo(f"Password changed for {result.username} (id={result.user_id}).")
        return
    if result.status is ChangeUserPasswordStatus.USER_NOT_FOUND:
        raise CliUserError(f"User not found: {result.username}")
    if result.status is ChangeUserPasswordStatus.SYSTEM_USER_DENIED:
        raise CliUserError("Cannot change the system user's password.")
    if result.status is ChangeUserPasswordStatus.INVALID_PASSWORD:
        message = "; ".join(result.errors) if result.errors else "Invalid password."
        raise CliUserError(f"Invalid password: {message}")


def _report_role_result(result: ChangeUserRoleCommandResult) -> None:
    if result.status is ChangeUserRoleStatus.CHANGED:
        message = " ".join(
            (
                f"Role changed for {result.username} (id={result.user_id})",
                f"to {result.role_name} (id={result.role_id}).",
            )
        )
        typer.echo(message)
        _report_authorization_refresh(result.authorization_refresh_status)
        return
    if result.status is ChangeUserRoleStatus.UNCHANGED:
        message = " ".join(
            (
                f"Role already set for {result.username} (id={result.user_id})",
                f"to {result.role_name} (id={result.role_id}).",
            )
        )
        typer.echo(message)
        _report_authorization_refresh(result.authorization_refresh_status)
        return
    if result.status is ChangeUserRoleStatus.USER_NOT_FOUND:
        raise CliUserError(f"User not found: {result.username}")
    if result.status is ChangeUserRoleStatus.ROLE_NOT_FOUND:
        raise CliUserError(f"Role not found: {result.role_name}")
    if result.status is ChangeUserRoleStatus.SYSTEM_USER_DENIED:
        raise CliUserError("Cannot change the system user's role.")


def _report_authorization_refresh(
    status: AuthorizationRefreshStatus | None,
) -> None:
    if status is AuthorizationRefreshStatus.REFRESHED:
        typer.echo("Active session authorization refreshed.")
        return
    if status is AuthorizationRefreshStatus.NO_ACTIVE_SESSION:
        typer.echo("No active session to refresh.")
        return
    if status is AuthorizationRefreshStatus.FAILED:
        typer.echo("Active session authorization refresh failed.")
