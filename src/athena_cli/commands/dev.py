from __future__ import annotations

import asyncio
import os
from typing import Annotated

import typer

from athena_cli.context import resolve_context, selected_environment_variable
from athena_cli.errors import CliUserError, map_cli_error
from athena_cli.prompts import PromptAdapter
from athena_cli.stable_verification.getscores import GetscoresVerifier
from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    StableSurface,
    StableTarget,
    SurfaceResult,
    VerificationStatus,
)
from athena_cli.stable_verification.reporting import StableVerificationReporter
from athena_cli.stable_verification.runner import (
    StableVerificationRunner,
    VerificationRunRequest,
)
from athena_cli.stable_verification.score_submit import ScoreSubmitVerifier
from osu_server.composition.management import (
    change_user_password as run_change_user_password,
)
from osu_server.composition.management import change_user_role as run_change_user_role
from osu_server.config import load_config, load_routing_config
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


def create_stable_verification_runner(target: StableTarget) -> StableVerificationRunner:
    _ = target
    return StableVerificationRunner(
        surface_executors={
            StableSurface.REGISTRATION: _catalog_only_executor(StableSurface.REGISTRATION),
            StableSurface.BANCHO_LOGIN: _catalog_only_executor(StableSurface.BANCHO_LOGIN),
            StableSurface.POLLING: _catalog_only_executor(StableSurface.POLLING),
            StableSurface.CHAT: _catalog_only_executor(StableSurface.CHAT),
            StableSurface.GETSCORES: _execute_getscores_verification,
            StableSurface.SCORE_SUBMIT: _execute_score_submit_verification,
        }
    )


def create_stable_verification_reporter() -> StableVerificationReporter:
    return StableVerificationReporter()


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


@app.command(name="stable-verify")
def stable_verify(
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="Running local Athena base URL."),
    ] = None,
    host: Annotated[
        str | None,
        typer.Option("--host", help="Stable host identity without osu. prefix."),
    ] = None,
    surface: Annotated[
        list[StableSurface] | None,
        typer.Option("--surface", help="Stable surface to verify. Repeat for multiple."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Render machine-readable JSON output."),
    ] = False,
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout", help="HTTP probe timeout in seconds."),
    ] = 2.0,
) -> None:
    try:
        exit_code = _stable_verify(
            environment=environment,
            base_url=base_url,
            host=host,
            surfaces=tuple(surface or ()),
            json_output=json_output,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc

    if exit_code != 0:
        raise typer.Exit(exit_code)


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


def _stable_verify(
    *,
    environment: str | None,
    base_url: str | None,
    host: str | None,
    surfaces: tuple[StableSurface, ...],
    json_output: bool,
    timeout_seconds: float,
) -> int:
    context = resolve_context(
        selected_environment=environment,
        process_environment=dict(os.environ),
    )
    if context.environment == "production":
        raise CliUserError(
            "Stable verification from the dev CLI is only available for development and test."
        )
    if base_url is None or not base_url.strip():
        raise CliUserError("--base-url is required for stable verification probes.")
    if timeout_seconds <= 0:
        raise CliUserError("--timeout must be greater than zero.")

    host_identity = host.strip() if host is not None and host.strip() else None
    if host_identity is None:
        with selected_environment_variable(context.environment):
            host_identity = load_routing_config().domain

    target = StableTarget(
        base_url=base_url,
        host_identity=host_identity,
        timeout_seconds=timeout_seconds,
    )
    runner = create_stable_verification_runner(target)
    result = runner.run(
        VerificationRunRequest(
            target=target,
            surfaces=surfaces,
        )
    )
    reporter = create_stable_verification_reporter()
    output = reporter.render_json(result) if json_output else reporter.render_text(result)
    typer.echo(output)

    return 1 if result.failed else 0


def _execute_score_submit_verification(
    request: VerificationRunRequest,
) -> tuple[SurfaceResult, ...]:
    _ = request
    return ScoreSubmitVerifier().verify_golden_response()


def _execute_getscores_verification(
    request: VerificationRunRequest,
) -> tuple[SurfaceResult, ...]:
    if request.target is None:
        return (
            _optional_probe_result(
                StableSurface.GETSCORES,
                "getscores local probe skipped: target not configured",
            ),
        )

    verifier: GetscoresVerifier[object] = GetscoresVerifier(target=request.target)
    results = list(verifier.verify_fixtures())
    try:
        cases = verifier.load_probe_cases()
    except (OSError, ValueError, TypeError) as exc:
        results.append(
            SurfaceResult(
                surface=StableSurface.GETSCORES,
                status=VerificationStatus.UNAVAILABLE,
                evidence_type=EvidenceType.HEADLESS_PROBE,
                scope=EvidenceScope.OPTIONAL,
                diagnostic_summary=DiagnosticSummary(
                    message=f"getscores probe case unavailable: {exc.__class__.__name__}"
                ),
                reference="tests/fixtures/stable_compatibility/getscores/probe_cases.json",
            )
        )
        return tuple(results)

    if not cases:
        results.append(
            _optional_probe_result(
                StableSurface.GETSCORES,
                "getscores local probe skipped: no probe cases configured",
            )
        )
        return tuple(results)

    results.append(verifier.probe_target(cases[0]))
    return tuple(results)


def _catalog_only_executor(
    surface: StableSurface,
):
    def execute(request: VerificationRunRequest) -> tuple[SurfaceResult, ...]:
        _ = request
        return (
            _optional_probe_result(
                surface,
                (
                    f"{surface.value} stable-verify live probe is not configured; "
                    "see evidence catalog"
                ),
            ),
        )

    return execute


def _optional_probe_result(surface: StableSurface, message: str) -> SurfaceResult:
    return SurfaceResult(
        surface=surface,
        status=VerificationStatus.SKIP,
        evidence_type=EvidenceType.HEADLESS_PROBE,
        scope=EvidenceScope.OPTIONAL,
        diagnostic_summary=DiagnosticSummary(message=message),
        reference="stable-verify catalog",
    )


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
