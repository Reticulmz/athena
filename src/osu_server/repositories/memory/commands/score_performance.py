"""In-memory command-side score performance repository."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.domain.scores.performance import (
    PerformanceCalculation,
    PerformanceCalculationState,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    ScorePerformanceCalculationClaimResult,
    ScorePerformanceCalculationRequestResult,
)
from osu_server.repositories.memory.commands.state import InMemoryPerformanceClaim

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.commands.score_performance import (
        ClaimScorePerformanceCalculation,
        CompleteScorePerformanceCalculation,
        CreateScorePerformanceCalculation,
        MarkScorePerformanceCalculationUnavailable,
    )
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryScorePerformanceCommandRepository:
    """Score performance command repository backed by active in-memory UoW state."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    async def create_or_reuse_calculation(
        self,
        command: CreateScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationRequestResult:
        current = await self.get_current_for_score(command.score_id)
        if current is None:
            return self._create_calculation(command, is_current=True, is_replacement=False)
        if _matches_request(current, command):
            return ScorePerformanceCalculationRequestResult(
                calculation=current,
                created=False,
                is_replacement=False,
            )

        replacement = self._get_replacement_for_score(command.score_id)
        if replacement is not None and _matches_request(replacement, command):
            return ScorePerformanceCalculationRequestResult(
                calculation=replacement,
                created=False,
                is_replacement=True,
            )

        if replacement is not None:
            self._state.performance_calculations_by_id[replacement.id or 0] = replace(
                replacement,
                state=PerformanceCalculationState.SUPERSEDED,
                is_current=False,
            )
        return self._create_calculation(command, is_current=False, is_replacement=True)

    async def claim_pending_calculation(
        self,
        command: ClaimScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationClaimResult | None:
        calculation = self._state.performance_calculations_by_id.get(command.calculation_id)
        if calculation is None or not calculation.state.is_pending:
            return None

        existing_claim = self._state.performance_claims_by_calculation_id.get(
            command.calculation_id
        )
        if existing_claim is not None and existing_claim.expires_at > command.claimed_at:
            return None

        attempt_count = 1 if existing_claim is None else existing_claim.attempt_count + 1
        claim = InMemoryPerformanceClaim(
            owner=command.owner,
            expires_at=command.claim_expires_at,
            attempt_count=attempt_count,
        )
        self._state.performance_claims_by_calculation_id[command.calculation_id] = claim
        return ScorePerformanceCalculationClaimResult(
            calculation=calculation,
            owner=claim.owner,
            expires_at=claim.expires_at,
            attempt_count=claim.attempt_count,
        )

    async def mark_completed(
        self,
        command: CompleteScorePerformanceCalculation,
    ) -> PerformanceCalculation | None:
        calculation = self._state.performance_calculations_by_id.get(command.calculation_id)
        if calculation is None:
            return None
        if not calculation.state.is_pending:
            return (
                calculation if calculation.state is PerformanceCalculationState.COMPLETED else None
            )

        completed = replace(
            calculation,
            state=PerformanceCalculationState.COMPLETED,
            pp=command.pp,
            star_rating=command.star_rating,
            calculator_name=command.calculator_name,
            calculator_version=command.calculator_version,
            formula_profile=command.formula_profile,
            beatmap_file_attachment_id=command.beatmap_file_attachment_id,
            beatmap_file_checksum_md5=command.beatmap_file_checksum_md5,
            unavailable_reason=None,
            calculated_at=command.calculated_at,
        )
        return self._finalize(completed)

    async def mark_unavailable(
        self,
        command: MarkScorePerformanceCalculationUnavailable,
    ) -> PerformanceCalculation | None:
        calculation = self._state.performance_calculations_by_id.get(command.calculation_id)
        if calculation is None:
            return None
        if not calculation.state.is_pending:
            return (
                calculation
                if calculation.state is PerformanceCalculationState.UNAVAILABLE
                else None
            )

        unavailable = replace(
            calculation,
            state=PerformanceCalculationState.UNAVAILABLE,
            pp=None,
            star_rating=None,
            calculator_name=command.calculator_name,
            calculator_version=command.calculator_version,
            formula_profile=command.formula_profile,
            beatmap_file_attachment_id=command.beatmap_file_attachment_id,
            beatmap_file_checksum_md5=command.beatmap_file_checksum_md5,
            unavailable_reason=command.reason,
            calculated_at=command.calculated_at,
        )
        return self._finalize(unavailable)

    async def get_by_id(self, calculation_id: int) -> PerformanceCalculation | None:
        return self._state.performance_calculations_by_id.get(calculation_id)

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        current_id = self._state.current_performance_calculation_id_by_score_id.get(score_id)
        if current_id is None:
            return None
        return self._state.performance_calculations_by_id.get(current_id)

    def _create_calculation(
        self,
        command: CreateScorePerformanceCalculation,
        *,
        is_current: bool,
        is_replacement: bool,
    ) -> ScorePerformanceCalculationRequestResult:
        calculation_id = self._state.next_performance_calculation_id
        self._state.next_performance_calculation_id += 1
        calculation = PerformanceCalculation(
            id=calculation_id,
            score_id=command.score_id,
            state=PerformanceCalculationState.QUEUED,
            is_current=is_current,
            pp=None,
            star_rating=None,
            calculator_name=command.calculator_name,
            calculator_version=command.calculator_version,
            formula_profile=command.formula_profile,
            beatmap_file_attachment_id=None,
            beatmap_file_checksum_md5=None,
            unavailable_reason=None,
            calculated_at=None,
        )
        self._state.performance_calculations_by_id[calculation_id] = calculation
        if is_current:
            self._state.current_performance_calculation_id_by_score_id[command.score_id] = (
                calculation_id
            )
        if is_replacement:
            self._state.replacement_performance_calculation_id_by_score_id[command.score_id] = (
                calculation_id
            )
        return ScorePerformanceCalculationRequestResult(
            calculation=calculation,
            created=True,
            is_replacement=is_replacement,
        )

    def _get_replacement_for_score(self, score_id: int) -> PerformanceCalculation | None:
        replacement_id = self._state.replacement_performance_calculation_id_by_score_id.get(
            score_id
        )
        if replacement_id is None:
            return None
        return self._state.performance_calculations_by_id.get(replacement_id)

    def _finalize(self, calculation: PerformanceCalculation) -> PerformanceCalculation:
        calculation_id = _require_calculation_id(calculation)
        if not calculation.is_current:
            old_current_id = self._state.current_performance_calculation_id_by_score_id.get(
                calculation.score_id
            )
            if old_current_id is not None and old_current_id != calculation_id:
                old_current = self._state.performance_calculations_by_id.get(old_current_id)
                if old_current is not None:
                    self._state.performance_calculations_by_id[old_current_id] = replace(
                        old_current,
                        state=PerformanceCalculationState.SUPERSEDED,
                        is_current=False,
                    )
            calculation = replace(calculation, is_current=True)
            self._state.current_performance_calculation_id_by_score_id[calculation.score_id] = (
                calculation_id
            )
            _ = self._state.replacement_performance_calculation_id_by_score_id.pop(
                calculation.score_id,
                None,
            )

        self._state.performance_calculations_by_id[calculation_id] = calculation
        _ = self._state.performance_claims_by_calculation_id.pop(calculation_id, None)
        return calculation


def _matches_request(
    calculation: PerformanceCalculation,
    command: CreateScorePerformanceCalculation,
) -> bool:
    return (
        calculation.calculator_name == command.calculator_name
        and calculation.calculator_version == command.calculator_version
        and calculation.formula_profile is command.formula_profile
    )


def _require_calculation_id(calculation: PerformanceCalculation) -> int:
    if calculation.id is None:
        msg = "performance calculation must have repository identity"
        raise ValueError(msg)
    return calculation.id
