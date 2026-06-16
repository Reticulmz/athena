"""Process durable score performance recalculation batch work."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, final

from osu_server.domain.scores.performance import PerformanceCalculationState
from osu_server.repositories.interfaces.commands.score_performance import (
    ClaimScorePerformanceRecalculationWork,
    CompleteScorePerformanceRecalculationWork,
    MarkScorePerformanceRecalculationWorkFailed,
    MarkScorePerformanceRecalculationWorkUnavailable,
)
from osu_server.services.commands.scores.performance.runtime import PerformanceRuntimeSettings

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.performance import PerformanceRecalculationWorkItem
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
    from osu_server.services.commands.scores.performance.create_recalculation_batch import (
        PerformanceCalculatorIdentity,
    )
    from osu_server.services.commands.scores.performance.request_calculation import (
        RequestPerformanceCalculationResult,
    )

from osu_server.services.commands.scores.performance.request_calculation import (
    RequestPerformanceCalculationCommand,
)


class ProcessPerformanceRecalculationBatchOutcome(Enum):
    """Observable outcome for one bounded recalculation batch processing pass."""

    PROCESSED = "processed"
    NO_WORK = "no_work"


@dataclass(frozen=True, slots=True)
class ProcessPerformanceRecalculationBatchCommand:
    """Command input for one recalculation batch worker pass."""

    batch_id: int
    claim_owner: str
    claimed_at: datetime

    def __post_init__(self) -> None:
        if self.batch_id <= 0:
            msg = "batch_id must be positive"
            raise ValueError(msg)
        if self.claim_owner == "":
            msg = "claim_owner must not be empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ProcessPerformanceRecalculationBatchResult:
    """Typed result for one recalculation batch processing pass."""

    outcome: ProcessPerformanceRecalculationBatchOutcome
    batch_id: int
    claimed_count: int = 0
    completed_count: int = 0
    unavailable_count: int = 0
    retryable_failure_count: int = 0
    finalization_conflict_count: int = 0


class PerformanceCalculationRequester(Protocol):
    """Request-use-case surface required by recalculation batch processing."""

    async def execute(
        self,
        command: RequestPerformanceCalculationCommand,
    ) -> RequestPerformanceCalculationResult: ...


@final
class ProcessPerformanceRecalculationBatchUseCase:
    """Claim durable recalculation work and drive replacement calculation requests."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        request_use_case: PerformanceCalculationRequester,
        calculator_identity: PerformanceCalculatorIdentity,
        settings: PerformanceRuntimeSettings | None = None,
    ) -> None:
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._request_use_case: PerformanceCalculationRequester = request_use_case
        self._calculator_identity: PerformanceCalculatorIdentity = calculator_identity
        self._settings: PerformanceRuntimeSettings = settings or PerformanceRuntimeSettings()

    async def execute(
        self,
        command: ProcessPerformanceRecalculationBatchCommand,
    ) -> ProcessPerformanceRecalculationBatchResult:
        """Process one bounded chunk of pending or stale recalculation work."""
        claimed = await self._claim_work(command)
        if len(claimed) == 0:
            return ProcessPerformanceRecalculationBatchResult(
                outcome=ProcessPerformanceRecalculationBatchOutcome.NO_WORK,
                batch_id=command.batch_id,
            )

        completed_count = 0
        unavailable_count = 0
        retryable_failure_count = 0
        finalization_conflict_count = 0

        for work_item in claimed:
            request_result = await self._request_replacement_calculation(command, work_item)
            outcome = await self._record_work_outcome(
                command=command,
                work_item=work_item,
                request_result=request_result,
            )
            if outcome is _WorkOutcome.COMPLETED:
                completed_count += 1
            elif outcome is _WorkOutcome.UNAVAILABLE:
                unavailable_count += 1
            elif outcome is _WorkOutcome.RETRYABLE_FAILURE:
                retryable_failure_count += 1
            else:
                finalization_conflict_count += 1

        return ProcessPerformanceRecalculationBatchResult(
            outcome=ProcessPerformanceRecalculationBatchOutcome.PROCESSED,
            batch_id=command.batch_id,
            claimed_count=len(claimed),
            completed_count=completed_count,
            unavailable_count=unavailable_count,
            retryable_failure_count=retryable_failure_count,
            finalization_conflict_count=finalization_conflict_count,
        )

    async def _claim_work(
        self,
        command: ProcessPerformanceRecalculationBatchCommand,
    ) -> tuple[PerformanceRecalculationWorkItem, ...]:
        async with self._unit_of_work_factory() as uow:
            claimed = await uow.score_performance.claim_recalculation_work(
                ClaimScorePerformanceRecalculationWork(
                    batch_id=command.batch_id,
                    owner=command.claim_owner,
                    claimed_at=command.claimed_at,
                    claim_expires_at=command.claimed_at + self._settings.claim_timeout,
                    limit=self._settings.worker_chunk_size,
                )
            )
            await uow.commit()
        return claimed

    async def _request_replacement_calculation(
        self,
        command: ProcessPerformanceRecalculationBatchCommand,
        work_item: PerformanceRecalculationWorkItem,
    ) -> RequestPerformanceCalculationResult:
        return await self._request_use_case.execute(
            RequestPerformanceCalculationCommand(
                score_id=work_item.score_id,
                calculator_name=self._calculator_identity.calculator_name(),
                calculator_version=self._calculator_identity.calculator_version(),
                requested_at=command.claimed_at,
            )
        )

    async def _record_work_outcome(
        self,
        *,
        command: ProcessPerformanceRecalculationBatchCommand,
        work_item: PerformanceRecalculationWorkItem,
        request_result: RequestPerformanceCalculationResult,
    ) -> _WorkOutcome:
        calculation = request_result.calculation
        if calculation is None:
            return await self._mark_work_failed(
                command=command,
                work_item=work_item,
                error=request_result.outcome.value,
            )
        if calculation.score_id != work_item.score_id:
            return await self._mark_work_failed(
                command=command,
                work_item=work_item,
                error="calculation_score_mismatch",
            )
        if calculation.state is PerformanceCalculationState.COMPLETED:
            return await self._mark_work_completed(
                command=command,
                work_item=work_item,
                calculation_id=_require_calculation_id(calculation.id),
            )
        if calculation.state is PerformanceCalculationState.UNAVAILABLE:
            return await self._mark_work_unavailable(
                command=command,
                work_item=work_item,
                calculation_id=_require_calculation_id(calculation.id),
                reason=calculation.unavailable_reason or "performance_unavailable",
            )
        if calculation.state.is_pending:
            return await self._mark_work_failed(
                command=command,
                work_item=work_item,
                error="replacement_calculation_pending",
            )
        return await self._mark_work_failed(
            command=command,
            work_item=work_item,
            error="replacement_calculation_not_terminal",
        )

    async def _mark_work_completed(
        self,
        *,
        command: ProcessPerformanceRecalculationBatchCommand,
        work_item: PerformanceRecalculationWorkItem,
        calculation_id: int,
    ) -> _WorkOutcome:
        async with self._unit_of_work_factory() as uow:
            updated = await uow.score_performance.mark_recalculation_work_completed(
                CompleteScorePerformanceRecalculationWork(
                    work_item_id=_require_work_item_id(work_item.id),
                    owner=command.claim_owner,
                    calculation_id=calculation_id,
                    completed_at=command.claimed_at,
                )
            )
            if updated is None:
                return _WorkOutcome.FINALIZATION_CONFLICT
            await uow.commit()
        return _WorkOutcome.COMPLETED

    async def _mark_work_unavailable(
        self,
        *,
        command: ProcessPerformanceRecalculationBatchCommand,
        work_item: PerformanceRecalculationWorkItem,
        calculation_id: int,
        reason: str,
    ) -> _WorkOutcome:
        async with self._unit_of_work_factory() as uow:
            updated = await uow.score_performance.mark_recalculation_work_unavailable(
                MarkScorePerformanceRecalculationWorkUnavailable(
                    work_item_id=_require_work_item_id(work_item.id),
                    owner=command.claim_owner,
                    calculation_id=calculation_id,
                    reason=reason,
                    completed_at=command.claimed_at,
                )
            )
            if updated is None:
                return _WorkOutcome.FINALIZATION_CONFLICT
            await uow.commit()
        return _WorkOutcome.UNAVAILABLE

    async def _mark_work_failed(
        self,
        *,
        command: ProcessPerformanceRecalculationBatchCommand,
        work_item: PerformanceRecalculationWorkItem,
        error: str,
    ) -> _WorkOutcome:
        async with self._unit_of_work_factory() as uow:
            updated = await uow.score_performance.mark_recalculation_work_failed(
                MarkScorePerformanceRecalculationWorkFailed(
                    work_item_id=_require_work_item_id(work_item.id),
                    owner=command.claim_owner,
                    error=error,
                    failed_at=command.claimed_at,
                )
            )
            if updated is None:
                return _WorkOutcome.FINALIZATION_CONFLICT
            await uow.commit()
        return _WorkOutcome.RETRYABLE_FAILURE


class _WorkOutcome(Enum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    RETRYABLE_FAILURE = "retryable_failure"
    FINALIZATION_CONFLICT = "finalization_conflict"


def _require_calculation_id(calculation_id: int | None) -> int:
    if calculation_id is None:
        msg = "performance calculation id must be assigned before work finalization"
        raise ValueError(msg)
    return calculation_id


def _require_work_item_id(work_item_id: int | None) -> int:
    if work_item_id is None:
        msg = "recalculation work item id must be assigned before finalization"
        raise ValueError(msg)
    return work_item_id


__all__ = (
    "PerformanceCalculationRequester",
    "ProcessPerformanceRecalculationBatchCommand",
    "ProcessPerformanceRecalculationBatchOutcome",
    "ProcessPerformanceRecalculationBatchResult",
    "ProcessPerformanceRecalculationBatchUseCase",
)
