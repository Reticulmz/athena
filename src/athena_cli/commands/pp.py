from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Annotated, Protocol, final

import typer

from athena_cli.context import (
    EnvironmentName,
    resolve_context,
    selected_environment_variable,
)
from athena_cli.errors import CliUserError, map_cli_error
from osu_server.composition.performance_cli import (
    create_performance_recalculation_batch_use_case,
)
from osu_server.config import load_config
from osu_server.domain.scores.score import Ruleset
from osu_server.services.commands.scores.performance import (
    CreatePerformanceRecalculationBatchCommand,
    CreatePerformanceRecalculationBatchMode,
    CreatePerformanceRecalculationBatchOutcome,
    CreatePerformanceRecalculationBatchResult,
)

app = typer.Typer(help="PP recalculation commands.")

_RULESET_BY_LABEL = {
    "osu": Ruleset.OSU,
    "taiko": Ruleset.TAIKO,
    "catch": Ruleset.CATCH,
    "mania": Ruleset.MANIA,
}
_SUPPORTED_RULESETS_LABEL = "osu, taiko, catch, mania"


class PerformanceRecalculationRunner(Protocol):
    async def run(
        self,
        *,
        environment: EnvironmentName,
        command: CreatePerformanceRecalculationBatchCommand,
    ) -> CreatePerformanceRecalculationBatchResult:
        """Run PP recalculation candidate selection or batch creation."""
        ...


@final
class CompositionPerformanceRecalculationRunner:
    async def run(
        self,
        *,
        environment: EnvironmentName,
        command: CreatePerformanceRecalculationBatchCommand,
    ) -> CreatePerformanceRecalculationBatchResult:
        with selected_environment_variable(environment):
            config = load_config()
        async with create_performance_recalculation_batch_use_case(config) as use_case:
            return await use_case.execute(command)


@app.callback()
def pp() -> None:
    """Manage PP recalculation operations."""


@app.command(name="recalculate")
def recalculate(
    score_id: Annotated[
        int | None,
        typer.Option("--score-id", help="Limit recalculation to one score id."),
    ] = None,
    beatmap_id: Annotated[
        int | None,
        typer.Option("--beatmap-id", help="Limit recalculation to one beatmap id."),
    ] = None,
    user_id: Annotated[
        int | None,
        typer.Option("--user-id", help="Limit recalculation to one user id."),
    ] = None,
    ruleset: Annotated[
        str | None,
        typer.Option("--ruleset", help=f"Limit by ruleset: {_SUPPORTED_RULESETS_LABEL}."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Optional candidate cap."),
    ] = None,
    full_scope: Annotated[
        bool,
        typer.Option("--all", help="Select all candidates when no narrow filter is present."),
    ] = False,
    include_unavailable: Annotated[
        bool,
        typer.Option(
            "--include-unavailable",
            help="Include unavailable current performance records.",
        ),
    ] = False,
    execute: Annotated[
        bool,
        typer.Option("--execute", help="Create durable recalculation work."),
    ] = False,
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
) -> None:
    try:
        _recalculate(
            score_id=score_id,
            beatmap_id=beatmap_id,
            user_id=user_id,
            ruleset=ruleset,
            limit=limit,
            full_scope=full_scope,
            include_unavailable=include_unavailable,
            execute=execute,
            environment=environment,
        )
    except Exception as exc:
        error = map_cli_error(exc)
        typer.echo(error.message, err=True)
        raise typer.Exit(error.exit_code) from exc


def create_recalculation_runner() -> PerformanceRecalculationRunner:
    return CompositionPerformanceRecalculationRunner()


def _recalculate(
    *,
    score_id: int | None,
    beatmap_id: int | None,
    user_id: int | None,
    ruleset: str | None,
    limit: int | None,
    full_scope: bool,
    include_unavailable: bool,
    execute: bool,
    environment: str | None,
) -> None:
    selected_ruleset = _parse_ruleset(ruleset)
    _validate_positive("score id", score_id)
    _validate_positive("beatmap id", beatmap_id)
    _validate_positive("user id", user_id)
    _validate_positive("limit", limit)
    _validate_scope(
        score_id=score_id,
        beatmap_id=beatmap_id,
        user_id=user_id,
        ruleset=selected_ruleset,
        full_scope=full_scope,
    )

    context = resolve_context(
        selected_environment=environment,
        process_environment=dict(os.environ),
    )
    command = CreatePerformanceRecalculationBatchCommand(
        mode=(
            CreatePerformanceRecalculationBatchMode.EXECUTE
            if execute
            else CreatePerformanceRecalculationBatchMode.DRY_RUN
        ),
        score_id=score_id,
        beatmap_id=beatmap_id,
        user_id=user_id,
        ruleset=selected_ruleset,
        limit=limit,
        full_scope=full_scope,
        include_unavailable=include_unavailable,
        requested_at=_now(),
    )
    result = asyncio.run(
        create_recalculation_runner().run(
            environment=context.environment,
            command=command,
        )
    )
    _report_result(result)


def _parse_ruleset(value: str | None) -> Ruleset | None:
    if value is None:
        return None
    normalized = value.lower()
    ruleset = _RULESET_BY_LABEL.get(normalized)
    if ruleset is None:
        msg = f"Unsupported ruleset {value!r}. Supported rulesets: {_SUPPORTED_RULESETS_LABEL}."
        raise CliUserError(msg)
    return ruleset


def _validate_positive(field_name: str, value: int | None) -> None:
    if value is not None and value <= 0:
        raise CliUserError(f"{field_name} must be positive.")


def _validate_scope(
    *,
    score_id: int | None,
    beatmap_id: int | None,
    user_id: int | None,
    ruleset: Ruleset | None,
    full_scope: bool,
) -> None:
    has_narrow_filter = any(
        value is not None for value in (score_id, beatmap_id, user_id, ruleset)
    )
    if full_scope and has_narrow_filter:
        raise CliUserError("Cannot combine --all with score, beatmap, user, or ruleset filters.")
    if not full_scope and not has_narrow_filter:
        raise CliUserError("Use --all or a narrow filter for full-scope recalculation.")


def _report_result(result: CreatePerformanceRecalculationBatchResult) -> None:
    if result.outcome is CreatePerformanceRecalculationBatchOutcome.DRY_RUN:
        typer.echo("PP recalculation dry-run")
        _print_candidate_breakdown(result)
        return
    if result.outcome is CreatePerformanceRecalculationBatchOutcome.CREATED:
        _print_created_batch(result)
        return
    if result.rejection_reason == "full_scope_required":
        raise CliUserError("Use --all or a narrow filter for full-scope recalculation.")
    reason = result.rejection_reason or "unknown reason"
    raise CliUserError(f"PP recalculation rejected: {reason}.")


def _print_created_batch(result: CreatePerformanceRecalculationBatchResult) -> None:
    batch = result.batch
    if batch is None or batch.id is None:
        msg = "created recalculation batch did not include a batch id"
        raise RuntimeError(msg)
    typer.echo("PP recalculation batch created")
    typer.echo(f"Batch ID: {batch.id}")
    _print_candidate_breakdown(result)
    if result.worker_wake_failed:
        error = result.worker_wake_error or "unknown error"
        typer.echo(f"Worker wake failed: {error}")


def _print_candidate_breakdown(
    result: CreatePerformanceRecalculationBatchResult,
) -> None:
    typer.echo(f"Candidates: {result.candidate_count}")
    if result.reason_counts:
        typer.echo("Reasons:")
        for reason, count in sorted(result.reason_counts.items()):
            typer.echo(f"  {reason}: {count}")
    else:
        typer.echo("Reasons: none")
    target = (
        f"Target: {result.target_calculator_name} "
        f"{result.target_calculator_version}, "
        f"{result.target_formula_profile.value}"
    )
    typer.echo(target)


def _now() -> datetime:
    return datetime.now(tz=UTC)


__all__ = (
    "CompositionPerformanceRecalculationRunner",
    "PerformanceRecalculationRunner",
    "app",
    "create_recalculation_runner",
    "recalculate",
)
