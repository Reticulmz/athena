"""Create score performance recalculation batch command use-case."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, final

from osu_server.domain.scores.performance import FormulaProfilePolicy
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.score_performance import (
    CreateScorePerformanceRecalculationBatch,
    CreateScorePerformanceRecalculationWorkItem,
)
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceCandidateSelection,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from osu_server.domain.scores.performance import (
        FormulaProfile,
        PerformanceRecalculationBatch,
    )
    from osu_server.repositories.interfaces.queries.score_performance import (
        RecalculationCandidateReason,
        ScorePerformanceQueryRepository,
        ScorePerformanceRecalculationCandidateResult,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory


class CreatePerformanceRecalculationBatchMode(Enum):
    """Operator-selected recalculation batch mode."""

    DRY_RUN = "dry_run"
    EXECUTE = "execute"


class CreatePerformanceRecalculationBatchOutcome(Enum):
    """Observable result of recalculation batch creation."""

    DRY_RUN = "dry_run"
    CREATED = "created"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class CreatePerformanceRecalculationBatchCommand:
    """Command input for selecting or creating durable recalculation work."""

    mode: CreatePerformanceRecalculationBatchMode
    score_id: int | None
    beatmap_id: int | None
    user_id: int | None
    ruleset: Ruleset | None
    limit: int | None
    full_scope: bool
    include_unavailable: bool
    requested_at: datetime

    def __post_init__(self) -> None:
        _validate_optional_positive("score_id", self.score_id)
        _validate_optional_positive("beatmap_id", self.beatmap_id)
        _validate_optional_positive("user_id", self.user_id)
        _validate_optional_positive("limit", self.limit)


@dataclass(frozen=True, slots=True)
class CreatePerformanceRecalculationBatchResult:
    """Typed result for dry-run or durable recalculation batch creation."""

    outcome: CreatePerformanceRecalculationBatchOutcome
    candidate_count: int
    reason_counts: Mapping[str, int]
    filters: Mapping[str, object]
    target_calculator_name: str
    target_calculator_version: str
    target_formula_profile: FormulaProfile
    batch: PerformanceRecalculationBatch | None = None
    worker_wake_requested: bool = False
    worker_wake_failed: bool = False
    worker_wake_error: str | None = None
    rejection_reason: str | None = None


class PerformanceCalculatorIdentity(Protocol):
    """Adapter-independent calculator identity boundary."""

    def calculator_name(self) -> str:
        """Return the active calculator implementation name."""
        ...

    def calculator_version(self) -> str:
        """Return the active calculator implementation version."""
        ...


class PerformanceRecalculationBatchWorkerWake(Protocol):
    """Adapter-independent boundary for waking recalculation batch workers."""

    async def wake_recalculation_batch(self, *, batch_id: int) -> None:
        """Wake durable recalculation batch processing."""
        ...


@final
class NoopPerformanceRecalculationBatchWorkerWake:
    """Worker wake boundary used before taskiq batch processing is wired."""

    async def wake_recalculation_batch(self, *, batch_id: int) -> None:
        """Intentionally do nothing."""
        _ = batch_id


class CreatePerformanceRecalculationBatchUseCase:
    """Select candidates and optionally create durable recalculation batch work."""

    def __init__(
        self,
        *,
        query_repository: ScorePerformanceQueryRepository,
        unit_of_work_factory: UnitOfWorkFactory,
        calculator_identity: PerformanceCalculatorIdentity,
        worker_wake: PerformanceRecalculationBatchWorkerWake | None = None,
        formula_profile_policy: FormulaProfilePolicy | None = None,
    ) -> None:
        self._query_repository: ScorePerformanceQueryRepository = query_repository
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._calculator_identity: PerformanceCalculatorIdentity = calculator_identity
        self._worker_wake: PerformanceRecalculationBatchWorkerWake = (
            worker_wake or NoopPerformanceRecalculationBatchWorkerWake()
        )
        self._formula_profile_policy: FormulaProfilePolicy = (
            formula_profile_policy or FormulaProfilePolicy()
        )

    async def execute(
        self,
        command: CreatePerformanceRecalculationBatchCommand,
    ) -> CreatePerformanceRecalculationBatchResult:
        """Execute dry-run selection or durable batch creation."""
        filters = _filters_from_command(command)
        target_calculator_name = self._calculator_identity.calculator_name()
        target_calculator_version = self._calculator_identity.calculator_version()
        target_formula_profile = self._formula_profile_policy.active_profile_for(Playstyle.VANILLA)

        if _requires_full_scope_confirmation(command):
            return CreatePerformanceRecalculationBatchResult(
                outcome=CreatePerformanceRecalculationBatchOutcome.REJECTED,
                candidate_count=0,
                reason_counts={},
                filters=filters,
                target_calculator_name=target_calculator_name,
                target_calculator_version=target_calculator_version,
                target_formula_profile=target_formula_profile,
                rejection_reason="full_scope_required",
            )

        selection = ScorePerformanceCandidateSelection(
            target_calculator_name=target_calculator_name,
            target_calculator_version=target_calculator_version,
            target_formula_profile=target_formula_profile,
            score_id=command.score_id,
            beatmap_id=command.beatmap_id,
            user_id=command.user_id,
            ruleset=command.ruleset,
            limit=command.limit,
            include_unavailable=command.include_unavailable,
        )
        selected = await self._query_repository.select_recalculation_candidates(selection)
        reason_counts = _reason_counts_as_strings(selected.reason_counts)

        if command.mode is CreatePerformanceRecalculationBatchMode.DRY_RUN:
            return CreatePerformanceRecalculationBatchResult(
                outcome=CreatePerformanceRecalculationBatchOutcome.DRY_RUN,
                candidate_count=selected.candidate_count,
                reason_counts=reason_counts,
                filters=filters,
                target_calculator_name=target_calculator_name,
                target_calculator_version=target_calculator_version,
                target_formula_profile=target_formula_profile,
            )

        return await self._create_batch(
            command=command,
            selected=selected,
            reason_counts=reason_counts,
            filters=filters,
            target_calculator_name=target_calculator_name,
            target_calculator_version=target_calculator_version,
            target_formula_profile=target_formula_profile,
        )

    async def _create_batch(
        self,
        *,
        command: CreatePerformanceRecalculationBatchCommand,
        selected: ScorePerformanceRecalculationCandidateResult,
        reason_counts: Mapping[str, int],
        filters: Mapping[str, object],
        target_calculator_name: str,
        target_calculator_version: str,
        target_formula_profile: FormulaProfile,
    ) -> CreatePerformanceRecalculationBatchResult:
        work_items = tuple(
            CreateScorePerformanceRecalculationWorkItem(
                score_id=candidate.score_id,
                reason=candidate.reason.value,
            )
            for candidate in selected.candidates
        )
        async with self._unit_of_work_factory() as uow:
            batch = await uow.score_performance.create_recalculation_batch(
                CreateScorePerformanceRecalculationBatch(
                    filters=filters,
                    reason_counts=reason_counts,
                    target_calculator_version=target_calculator_version,
                    target_formula_profile=target_formula_profile,
                    work_items=work_items,
                    created_at=command.requested_at,
                )
            )
            await uow.commit()

        wake_requested = len(work_items) > 0
        wake_failed = False
        wake_error: str | None = None

        if wake_requested:
            batch_id = batch.id
            if batch_id is None:
                msg = "recalculation batch id must be assigned before worker wake"
                raise ValueError(msg)
            try:
                await self._worker_wake.wake_recalculation_batch(batch_id=batch_id)
            except Exception as exc:
                wake_failed = True
                wake_error = str(exc)

        return CreatePerformanceRecalculationBatchResult(
            outcome=CreatePerformanceRecalculationBatchOutcome.CREATED,
            candidate_count=selected.candidate_count,
            reason_counts=reason_counts,
            filters=filters,
            target_calculator_name=target_calculator_name,
            target_calculator_version=target_calculator_version,
            target_formula_profile=target_formula_profile,
            batch=batch,
            worker_wake_requested=wake_requested,
            worker_wake_failed=wake_failed,
            worker_wake_error=wake_error,
        )


def _validate_optional_positive(field_name: str, value: int | None) -> None:
    if value is not None and value <= 0:
        msg = f"{field_name} must be positive"
        raise ValueError(msg)


def _filters_from_command(
    command: CreatePerformanceRecalculationBatchCommand,
) -> Mapping[str, object]:
    return {
        "score_id": command.score_id,
        "beatmap_id": command.beatmap_id,
        "user_id": command.user_id,
        "ruleset": command.ruleset.name.lower() if command.ruleset is not None else None,
        "limit": command.limit,
        "full_scope": command.full_scope,
        "include_unavailable": command.include_unavailable,
    }


def _requires_full_scope_confirmation(
    command: CreatePerformanceRecalculationBatchCommand,
) -> bool:
    return (
        command.mode is CreatePerformanceRecalculationBatchMode.EXECUTE
        and not command.full_scope
        and not _has_narrow_filter(command)
    )


def _has_narrow_filter(command: CreatePerformanceRecalculationBatchCommand) -> bool:
    return (
        command.score_id is not None
        or command.beatmap_id is not None
        or command.user_id is not None
        or command.ruleset is not None
    )


def _reason_counts_as_strings(
    reason_counts: Mapping[RecalculationCandidateReason, int],
) -> Mapping[str, int]:
    return {reason.value: count for reason, count in reason_counts.items()}


__all__ = (
    "CreatePerformanceRecalculationBatchCommand",
    "CreatePerformanceRecalculationBatchMode",
    "CreatePerformanceRecalculationBatchOutcome",
    "CreatePerformanceRecalculationBatchResult",
    "CreatePerformanceRecalculationBatchUseCase",
    "NoopPerformanceRecalculationBatchWorkerWake",
    "PerformanceCalculatorIdentity",
    "PerformanceRecalculationBatchWorkerWake",
)
