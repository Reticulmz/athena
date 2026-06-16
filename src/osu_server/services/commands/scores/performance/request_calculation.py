"""Request score performance calculation command use-case."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, final

from osu_server.domain.scores.performance import (
    FormulaProfilePolicy,
    PerformanceEligibilityPolicy,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    CreateScorePerformanceCalculation,
    ScorePerformanceCommandConflictError,
)

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.performance import PerformanceCalculation
    from osu_server.repositories.interfaces.commands.score_performance import (
        ScorePerformanceCalculationRequestResult,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory


class RequestPerformanceCalculationOutcome(Enum):
    """Observable result of a calculation request command."""

    CREATED = "created"
    CREATED_REPLACEMENT = "created_replacement"
    REUSED_PENDING = "reused_pending"
    REUSED_REPLACEMENT_PENDING = "reused_replacement_pending"
    ALREADY_CURRENT = "already_current"
    SKIPPED_OUT_OF_SCOPE = "skipped_out_of_scope"
    SCORE_NOT_FOUND = "score_not_found"
    TEMPORARY_CONFLICT = "temporary_conflict"


@dataclass(frozen=True, slots=True)
class RequestPerformanceCalculationCommand:
    """Command input for requesting performance calculation for one accepted score."""

    score_id: int
    calculator_name: str
    calculator_version: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class RequestPerformanceCalculationResult:
    """Typed result for performance calculation request workflow."""

    outcome: RequestPerformanceCalculationOutcome
    score_id: int
    calculation: PerformanceCalculation | None = None
    eligibility_reason: str | None = None
    created: bool = False
    is_replacement: bool = False
    worker_wake_requested: bool = False
    worker_wake_failed: bool = False
    worker_wake_error: str | None = None


class PerformanceCalculationWorkerWake(Protocol):
    """Adapter-independent boundary for waking calculation workers."""

    async def wake_score_calculation(self, *, score_id: int, calculation_id: int) -> None:
        """Wake score performance processing for a durable calculation row."""
        ...


@final
class NoopPerformanceCalculationWorkerWake:
    """Worker wake boundary used before taskiq job wiring exists."""

    async def wake_score_calculation(self, *, score_id: int, calculation_id: int) -> None:
        """Intentionally do nothing."""
        _ = score_id
        _ = calculation_id


class RequestPerformanceCalculationUseCase:
    """Create or reuse a durable performance calculation request for one score."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        worker_wake: PerformanceCalculationWorkerWake | None = None,
        eligibility_policy: PerformanceEligibilityPolicy | None = None,
        formula_profile_policy: FormulaProfilePolicy | None = None,
    ) -> None:
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._worker_wake: PerformanceCalculationWorkerWake = (
            worker_wake or NoopPerformanceCalculationWorkerWake()
        )
        self._eligibility_policy: PerformanceEligibilityPolicy = (
            eligibility_policy or PerformanceEligibilityPolicy()
        )
        self._formula_profile_policy: FormulaProfilePolicy = (
            formula_profile_policy or FormulaProfilePolicy()
        )

    async def execute(
        self,
        command: RequestPerformanceCalculationCommand,
    ) -> RequestPerformanceCalculationResult:
        """Execute the request workflow inside the command persistence boundary."""
        async with self._unit_of_work_factory() as uow:
            score = await uow.scores.get_by_id(command.score_id)
            if score is None:
                return RequestPerformanceCalculationResult(
                    outcome=RequestPerformanceCalculationOutcome.SCORE_NOT_FOUND,
                    score_id=command.score_id,
                )

            eligibility = self._eligibility_policy.evaluate(score)
            if not eligibility.is_eligible:
                return RequestPerformanceCalculationResult(
                    outcome=RequestPerformanceCalculationOutcome.SKIPPED_OUT_OF_SCOPE,
                    score_id=command.score_id,
                    eligibility_reason=eligibility.reason,
                )

            formula_profile = self._formula_profile_policy.active_profile_for(score.playstyle)
            try:
                request_result = await uow.score_performance.create_or_reuse_calculation(
                    CreateScorePerformanceCalculation(
                        score_id=command.score_id,
                        calculator_name=command.calculator_name,
                        calculator_version=command.calculator_version,
                        formula_profile=formula_profile,
                        requested_at=command.requested_at,
                    )
                )
            except ScorePerformanceCommandConflictError:
                return RequestPerformanceCalculationResult(
                    outcome=RequestPerformanceCalculationOutcome.TEMPORARY_CONFLICT,
                    score_id=command.score_id,
                )

            if request_result.requires_commit:
                await uow.commit()

        return await self._result_after_commit(command.score_id, request_result)

    async def _result_after_commit(
        self,
        score_id: int,
        request_result: ScorePerformanceCalculationRequestResult,
    ) -> RequestPerformanceCalculationResult:
        outcome = _outcome_from_request_result(request_result)
        should_wake = request_result.calculation.state.is_pending
        wake_failed = False
        wake_error: str | None = None

        if should_wake:
            calculation_id = request_result.calculation.id
            if calculation_id is None:
                msg = "performance calculation id must be assigned before worker wake"
                raise ValueError(msg)
            try:
                await self._worker_wake.wake_score_calculation(
                    score_id=score_id,
                    calculation_id=calculation_id,
                )
            except Exception as exc:
                wake_failed = True
                wake_error = str(exc)

        return RequestPerformanceCalculationResult(
            outcome=outcome,
            score_id=score_id,
            calculation=request_result.calculation,
            created=request_result.created,
            is_replacement=request_result.is_replacement,
            worker_wake_requested=should_wake,
            worker_wake_failed=wake_failed,
            worker_wake_error=wake_error,
        )


def _outcome_from_request_result(
    request_result: ScorePerformanceCalculationRequestResult,
) -> RequestPerformanceCalculationOutcome:
    if request_result.created:
        if request_result.is_replacement:
            return RequestPerformanceCalculationOutcome.CREATED_REPLACEMENT
        return RequestPerformanceCalculationOutcome.CREATED

    if request_result.calculation.state.is_pending:
        if request_result.is_replacement:
            return RequestPerformanceCalculationOutcome.REUSED_REPLACEMENT_PENDING
        return RequestPerformanceCalculationOutcome.REUSED_PENDING

    return RequestPerformanceCalculationOutcome.ALREADY_CURRENT


__all__ = (
    "NoopPerformanceCalculationWorkerWake",
    "PerformanceCalculationWorkerWake",
    "RequestPerformanceCalculationCommand",
    "RequestPerformanceCalculationOutcome",
    "RequestPerformanceCalculationResult",
    "RequestPerformanceCalculationUseCase",
)
