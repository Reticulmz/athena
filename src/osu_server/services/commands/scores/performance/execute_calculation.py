"""Execute score performance calculation command use-case."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, final

from osu_server.domain.scores.performance import (
    PerformanceCalculationState,
    PerformanceEligibilityPolicy,
)
from osu_server.domain.scores.user_stats import UserStatsPolicy
from osu_server.infrastructure.performance import (
    PerformanceCalculatorCompleted,
    PerformanceCalculatorInput,
    PerformanceCalculatorUnavailable,
)
from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
    PerformanceCompletionSignalPayload,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    ClaimScorePerformanceCalculation,
    CompleteScorePerformanceCalculation,
    MarkScorePerformanceCalculationUnavailable,
    UpdateScorePerformanceCalculationState,
)
from osu_server.services.commands.scores.performance.beatmap_file_provider import (
    PerformanceBeatmapFilePending,
    PerformanceBeatmapFilePendingReason,
    PerformanceBeatmapFileQuery,
    PerformanceBeatmapFileReady,
    PerformanceBeatmapFileUnavailable,
)
from osu_server.services.commands.scores.performance.projection_refresh import (
    refresh_performance_best_for_current_score,
)
from osu_server.services.commands.scores.performance.runtime import (
    PerformanceRuntimeSettings,
)
from osu_server.services.commands.scores.user_stats_projection import (
    replace_current_user_stats_projection,
)

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.performance import PerformanceCalculation
    from osu_server.domain.scores.score import Score
    from osu_server.infrastructure.performance import PerformanceCalculator
    from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
        PerformanceCompletionSignal,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
    from osu_server.services.commands.scores.performance.beatmap_file_provider import (
        PerformanceBeatmapFileProvider,
    )


class ExecutePerformanceCalculationOutcome(Enum):
    """Observable result of worker-side performance calculation execution."""

    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    PENDING_INPUT = "pending_input"
    CLAIM_NOT_ACQUIRED = "claim_not_acquired"
    SCORE_NOT_FOUND = "score_not_found"
    FINALIZATION_CONFLICT = "finalization_conflict"


@dataclass(frozen=True, slots=True)
class ExecutePerformanceCalculationCommand:
    """Command input for claiming and executing one performance calculation."""

    calculation_id: int
    claim_owner: str
    claimed_at: datetime

    def __post_init__(self) -> None:
        if self.calculation_id <= 0:
            msg = "calculation_id must be positive"
            raise ValueError(msg)
        if self.claim_owner == "":
            msg = "claim_owner must not be empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ExecutePerformanceCalculationResult:
    """Typed result for worker-side performance calculation execution."""

    outcome: ExecutePerformanceCalculationOutcome
    calculation_id: int
    score_id: int | None = None
    calculation: PerformanceCalculation | None = None
    pending_reason: PerformanceBeatmapFilePendingReason | None = None
    unavailable_reason: str | None = None
    signal_notified: bool = False
    signal_failed: bool = False
    signal_error: str | None = None


@dataclass(frozen=True, slots=True)
class _ClaimedCalculation:
    calculation: PerformanceCalculation
    score: Score


@final
class ExecutePerformanceCalculationUseCase:
    """Claim, calculate, finalize, and signal one pending performance row."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        beatmap_file_provider: PerformanceBeatmapFileProvider,
        calculator: PerformanceCalculator,
        completion_signal: PerformanceCompletionSignal,
        settings: PerformanceRuntimeSettings | None = None,
        eligibility_policy: PerformanceEligibilityPolicy | None = None,
        user_stats_policy: UserStatsPolicy | None = None,
    ) -> None:
        """PP 計算実行に必要な依存を受け取る。"""
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._beatmap_file_provider: PerformanceBeatmapFileProvider = beatmap_file_provider
        self._calculator: PerformanceCalculator = calculator
        self._completion_signal: PerformanceCompletionSignal = completion_signal
        self._settings: PerformanceRuntimeSettings = settings or PerformanceRuntimeSettings()
        self._eligibility_policy: PerformanceEligibilityPolicy = (
            eligibility_policy or PerformanceEligibilityPolicy()
        )
        self._user_stats_policy: UserStatsPolicy = user_stats_policy or UserStatsPolicy()

    async def execute(
        self,
        command: ExecutePerformanceCalculationCommand,
    ) -> ExecutePerformanceCalculationResult:
        """Execute worker-side performance calculation without transport concerns."""
        claimed = await self._claim_calculation(command)
        if isinstance(claimed, ExecutePerformanceCalculationResult):
            return claimed

        file_result = await self._beatmap_file_provider.provide(
            PerformanceBeatmapFileQuery(claimed.score.beatmap_id)
        )
        if isinstance(file_result, PerformanceBeatmapFilePending):
            return ExecutePerformanceCalculationResult(
                outcome=ExecutePerformanceCalculationOutcome.PENDING_INPUT,
                calculation_id=command.calculation_id,
                score_id=claimed.score.id,
                calculation=claimed.calculation,
                pending_reason=file_result.reason,
            )

        return await self._finalize_from_file_result(
            command=command,
            claimed=claimed,
            file_result=file_result,
        )

    async def _claim_calculation(
        self,
        command: ExecutePerformanceCalculationCommand,
    ) -> _ClaimedCalculation | ExecutePerformanceCalculationResult:
        claim_expires_at = command.claimed_at + self._settings.claim_timeout
        async with self._unit_of_work_factory() as uow:
            claim = await uow.score_performance.claim_pending_calculation(
                ClaimScorePerformanceCalculation(
                    calculation_id=command.calculation_id,
                    owner=command.claim_owner,
                    claimed_at=command.claimed_at,
                    claim_expires_at=claim_expires_at,
                )
            )
            if claim is None:
                return ExecutePerformanceCalculationResult(
                    outcome=ExecutePerformanceCalculationOutcome.CLAIM_NOT_ACQUIRED,
                    calculation_id=command.calculation_id,
                )

            calculation = claim.calculation
            score = await uow.scores.get_by_id(calculation.score_id)
            if score is None:
                unavailable = await uow.score_performance.mark_unavailable(
                    MarkScorePerformanceCalculationUnavailable(
                        calculation_id=command.calculation_id,
                        calculator_name=self._calculator.calculator_name(),
                        calculator_version=self._calculator.calculator_version(),
                        formula_profile=calculation.formula_profile,
                        beatmap_file_attachment_id=None,
                        beatmap_file_checksum_md5=None,
                        reason="score_not_found",
                        calculated_at=command.claimed_at,
                    )
                )
                if unavailable is None:
                    return ExecutePerformanceCalculationResult(
                        outcome=ExecutePerformanceCalculationOutcome.FINALIZATION_CONFLICT,
                        calculation_id=command.calculation_id,
                        score_id=calculation.score_id,
                    )
                await uow.commit()
                result = await self._result_after_terminal_commit(unavailable)
                return ExecutePerformanceCalculationResult(
                    outcome=ExecutePerformanceCalculationOutcome.SCORE_NOT_FOUND,
                    calculation_id=result.calculation_id,
                    score_id=result.score_id,
                    calculation=result.calculation,
                    unavailable_reason=result.unavailable_reason,
                    signal_notified=result.signal_notified,
                    signal_failed=result.signal_failed,
                    signal_error=result.signal_error,
                )

            if calculation.state is PerformanceCalculationState.QUEUED:
                calculation = await uow.score_performance.update_pending_calculation_state(
                    UpdateScorePerformanceCalculationState(
                        calculation_id=command.calculation_id,
                        expected_state=PerformanceCalculationState.QUEUED,
                        state=PerformanceCalculationState.FETCHING_FILE,
                        transitioned_at=command.claimed_at,
                    )
                )
                if calculation is None:
                    return ExecutePerformanceCalculationResult(
                        outcome=ExecutePerformanceCalculationOutcome.FINALIZATION_CONFLICT,
                        calculation_id=command.calculation_id,
                        score_id=claim.calculation.score_id,
                    )

            await uow.commit()

        return _ClaimedCalculation(calculation=calculation, score=score)

    async def _transition_pending_state(
        self,
        *,
        command: ExecutePerformanceCalculationCommand,
        score_id: int,
        expected_state: PerformanceCalculationState,
        state: PerformanceCalculationState,
    ) -> PerformanceCalculation | ExecutePerformanceCalculationResult:
        async with self._unit_of_work_factory() as uow:
            calculation = await uow.score_performance.update_pending_calculation_state(
                UpdateScorePerformanceCalculationState(
                    calculation_id=command.calculation_id,
                    expected_state=expected_state,
                    state=state,
                    transitioned_at=command.claimed_at,
                )
            )
            if calculation is None:
                return ExecutePerformanceCalculationResult(
                    outcome=ExecutePerformanceCalculationOutcome.FINALIZATION_CONFLICT,
                    calculation_id=command.calculation_id,
                    score_id=score_id,
                )
            await uow.commit()
        return calculation

    async def _finalize_from_file_result(
        self,
        *,
        command: ExecutePerformanceCalculationCommand,
        claimed: _ClaimedCalculation,
        file_result: PerformanceBeatmapFileReady | PerformanceBeatmapFileUnavailable,
    ) -> ExecutePerformanceCalculationResult:
        if isinstance(file_result, PerformanceBeatmapFileUnavailable):
            return await self._finalize_unavailable(
                command=command,
                score_id=claimed.calculation.score_id,
                score=claimed.score,
                calculation=claimed.calculation,
                file_result=file_result,
                reason=file_result.reason.value,
            )

        calculating = claimed.calculation
        if claimed.calculation.state is PerformanceCalculationState.FETCHING_FILE:
            transitioned = await self._transition_pending_state(
                command=command,
                score_id=claimed.calculation.score_id,
                expected_state=PerformanceCalculationState.FETCHING_FILE,
                state=PerformanceCalculationState.CALCULATING,
            )
            if isinstance(transitioned, ExecutePerformanceCalculationResult):
                return transitioned
            calculating = transitioned
        elif claimed.calculation.state is not PerformanceCalculationState.CALCULATING:
            return ExecutePerformanceCalculationResult(
                outcome=ExecutePerformanceCalculationOutcome.FINALIZATION_CONFLICT,
                calculation_id=command.calculation_id,
                score_id=claimed.calculation.score_id,
            )

        calculator_result = self._calculator.calculate(
            PerformanceCalculatorInput(
                score=claimed.score,
                osu_file_bytes=file_result.osu_file_bytes,
            )
        )
        if isinstance(calculator_result, PerformanceCalculatorUnavailable):
            return await self._finalize_unavailable(
                command=command,
                score_id=claimed.calculation.score_id,
                score=claimed.score,
                calculation=calculating,
                file_result=file_result,
                reason=calculator_result.reason.value,
            )

        return await self._finalize_completed(
            command=command,
            score_id=claimed.calculation.score_id,
            score=claimed.score,
            calculation=calculating,
            file_result=file_result,
            calculator_result=calculator_result,
        )

    async def _finalize_completed(
        self,
        *,
        command: ExecutePerformanceCalculationCommand,
        score_id: int,
        score: Score,
        calculation: PerformanceCalculation,
        file_result: PerformanceBeatmapFileReady,
        calculator_result: PerformanceCalculatorCompleted,
    ) -> ExecutePerformanceCalculationResult:
        async with self._unit_of_work_factory() as uow:
            finalized = await uow.score_performance.mark_completed(
                CompleteScorePerformanceCalculation(
                    calculation_id=command.calculation_id,
                    pp=calculator_result.pp,
                    star_rating=calculator_result.star_rating,
                    calculator_name=self._calculator.calculator_name(),
                    calculator_version=self._calculator.calculator_version(),
                    formula_profile=calculation.formula_profile,
                    beatmap_file_attachment_id=(file_result.provenance.beatmap_file_attachment_id),
                    beatmap_file_checksum_md5=file_result.provenance.checksum_md5,
                    calculated_at=command.claimed_at,
                )
            )
            if finalized is None:
                return ExecutePerformanceCalculationResult(
                    outcome=ExecutePerformanceCalculationOutcome.FINALIZATION_CONFLICT,
                    calculation_id=command.calculation_id,
                    score_id=score_id,
                )
            _ = await refresh_performance_best_for_current_score(
                uow,
                score=score,
                calculation=finalized,
                eligibility_policy=self._eligibility_policy,
            )
            _ = await replace_current_user_stats_projection(
                uow,
                user_id=score.user_id,
                ruleset=score.ruleset,
                playstyle=score.playstyle,
                policy=self._user_stats_policy,
            )
            await uow.commit()

        result = await self._result_after_terminal_commit(finalized)
        return ExecutePerformanceCalculationResult(
            outcome=ExecutePerformanceCalculationOutcome.COMPLETED,
            calculation_id=result.calculation_id,
            score_id=result.score_id,
            calculation=result.calculation,
            signal_notified=result.signal_notified,
            signal_failed=result.signal_failed,
            signal_error=result.signal_error,
        )

    async def _finalize_unavailable(
        self,
        *,
        command: ExecutePerformanceCalculationCommand,
        score_id: int,
        score: Score,
        calculation: PerformanceCalculation,
        file_result: PerformanceBeatmapFileReady | PerformanceBeatmapFileUnavailable,
        reason: str,
    ) -> ExecutePerformanceCalculationResult:
        provenance = file_result.provenance
        async with self._unit_of_work_factory() as uow:
            finalized = await uow.score_performance.mark_unavailable(
                MarkScorePerformanceCalculationUnavailable(
                    calculation_id=command.calculation_id,
                    calculator_name=self._calculator.calculator_name(),
                    calculator_version=self._calculator.calculator_version(),
                    formula_profile=calculation.formula_profile,
                    beatmap_file_attachment_id=(
                        None if provenance is None else provenance.beatmap_file_attachment_id
                    ),
                    beatmap_file_checksum_md5=(
                        None if provenance is None else provenance.checksum_md5
                    ),
                    reason=reason,
                    calculated_at=command.claimed_at,
                )
            )
            if finalized is None:
                return ExecutePerformanceCalculationResult(
                    outcome=ExecutePerformanceCalculationOutcome.FINALIZATION_CONFLICT,
                    calculation_id=command.calculation_id,
                    score_id=score_id,
                    unavailable_reason=reason,
                )
            _ = await refresh_performance_best_for_current_score(
                uow,
                score=score,
                calculation=finalized,
                eligibility_policy=self._eligibility_policy,
            )
            _ = await replace_current_user_stats_projection(
                uow,
                user_id=score.user_id,
                ruleset=score.ruleset,
                playstyle=score.playstyle,
                policy=self._user_stats_policy,
            )
            await uow.commit()

        result = await self._result_after_terminal_commit(finalized)
        return ExecutePerformanceCalculationResult(
            outcome=ExecutePerformanceCalculationOutcome.UNAVAILABLE,
            calculation_id=result.calculation_id,
            score_id=result.score_id,
            calculation=result.calculation,
            unavailable_reason=reason,
            signal_notified=result.signal_notified,
            signal_failed=result.signal_failed,
            signal_error=result.signal_error,
        )

    async def _result_after_terminal_commit(
        self,
        calculation: PerformanceCalculation,
    ) -> ExecutePerformanceCalculationResult:
        calculation_id = calculation.id
        if calculation_id is None:
            msg = "performance calculation id must be assigned before completion signal"
            raise ValueError(msg)

        signal_failed = False
        signal_error: str | None = None
        try:
            await self._completion_signal.notify(
                PerformanceCompletionSignalPayload(
                    score_id=calculation.score_id,
                    calculation_id=calculation_id,
                    state=calculation.state,
                )
            )
        except Exception as exc:
            signal_failed = True
            signal_error = str(exc)

        return ExecutePerformanceCalculationResult(
            outcome=(
                ExecutePerformanceCalculationOutcome.COMPLETED
                if calculation.state is PerformanceCalculationState.COMPLETED
                else ExecutePerformanceCalculationOutcome.UNAVAILABLE
            ),
            calculation_id=calculation_id,
            score_id=calculation.score_id,
            calculation=calculation,
            unavailable_reason=calculation.unavailable_reason,
            signal_notified=not signal_failed,
            signal_failed=signal_failed,
            signal_error=signal_error,
        )


__all__ = (
    "ExecutePerformanceCalculationCommand",
    "ExecutePerformanceCalculationOutcome",
    "ExecutePerformanceCalculationResult",
    "ExecutePerformanceCalculationUseCase",
)
