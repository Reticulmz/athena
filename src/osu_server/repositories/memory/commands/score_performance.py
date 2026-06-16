"""In-memory command-side score performance repository."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.domain.scores.performance import (
    PerformanceCalculation,
    PerformanceCalculationState,
    PerformanceRecalculationBatch,
    PerformanceRecalculationBatchStatus,
    PerformanceRecalculationWorkItem,
    PerformanceRecalculationWorkItemState,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    ScorePerformanceCalculationClaimResult,
    ScorePerformanceCalculationRequestResult,
)
from osu_server.repositories.memory.commands.state import (
    InMemoryPerformanceClaim,
    InMemoryPerformanceRecalculationBatchRecord,
    InMemoryPerformanceRecalculationWorkItemRecord,
)

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.repositories.interfaces.commands.score_performance import (
        ClaimScorePerformanceCalculation,
        ClaimScorePerformanceRecalculationWork,
        CompleteScorePerformanceCalculation,
        CompleteScorePerformanceRecalculationWork,
        CreateScorePerformanceCalculation,
        CreateScorePerformanceRecalculationBatch,
        MarkScorePerformanceCalculationUnavailable,
        MarkScorePerformanceRecalculationWorkFailed,
        MarkScorePerformanceRecalculationWorkUnavailable,
        UpdateScorePerformanceCalculationState,
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

    async def update_pending_calculation_state(
        self,
        command: UpdateScorePerformanceCalculationState,
    ) -> PerformanceCalculation | None:
        calculation = self._state.performance_calculations_by_id.get(command.calculation_id)
        if calculation is None or not calculation.state.is_pending:
            return None
        if calculation.state is not command.expected_state:
            return None

        updated = replace(calculation, state=command.state)
        self._state.performance_calculations_by_id[command.calculation_id] = updated
        return updated

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

    async def create_recalculation_batch(
        self,
        command: CreateScorePerformanceRecalculationBatch,
    ) -> PerformanceRecalculationBatch:
        batch_id = self._state.next_performance_recalculation_batch_id
        self._state.next_performance_recalculation_batch_id += 1
        batch_status = (
            PerformanceRecalculationBatchStatus.COMPLETED
            if len(command.work_items) == 0
            else PerformanceRecalculationBatchStatus.PENDING
        )
        batch = InMemoryPerformanceRecalculationBatchRecord(
            id=batch_id,
            status=batch_status.value,
            filters=dict(command.filters),
            reason_counts=dict(command.reason_counts),
            target_calculator_version=command.target_calculator_version,
            target_formula_profile=command.target_formula_profile,
            candidate_count=len(command.work_items),
            completed_count=0,
            unavailable_count=0,
            created_at=command.created_at,
            updated_at=command.created_at,
        )
        self._state.performance_recalculation_batches_by_id[batch_id] = batch
        self._state.performance_recalculation_work_item_ids_by_batch_id[batch_id] = []

        for work in command.work_items:
            work_item_id = self._state.next_performance_recalculation_work_item_id
            self._state.next_performance_recalculation_work_item_id += 1
            work_item = InMemoryPerformanceRecalculationWorkItemRecord(
                id=work_item_id,
                batch_id=batch_id,
                score_id=work.score_id,
                reason=work.reason,
                state=PerformanceRecalculationWorkItemState.PENDING.value,
                calculation_id=None,
                claim=None,
                attempt_count=0,
                last_error=None,
                created_at=command.created_at,
                updated_at=command.created_at,
            )
            self._state.performance_recalculation_work_items_by_id[work_item_id] = work_item
            self._state.performance_recalculation_work_item_ids_by_batch_id[batch_id].append(
                work_item_id
            )

        return self._batch_to_domain(batch)

    async def claim_recalculation_work(
        self,
        command: ClaimScorePerformanceRecalculationWork,
    ) -> tuple[PerformanceRecalculationWorkItem, ...]:
        if command.limit <= 0:
            msg = "recalculation work claim limit must be positive"
            raise ValueError(msg)

        batch = self._state.performance_recalculation_batches_by_id.get(command.batch_id)
        if batch is None:
            return ()

        claimable = [
            item
            for item in self._work_items_for_batch(command.batch_id)
            if _is_recalculation_work_claimable(item, command.claimed_at)
        ][: command.limit]
        if len(claimable) == 0:
            return ()

        claimed_items: list[PerformanceRecalculationWorkItem] = []
        for item in claimable:
            attempt_count = item.attempt_count + 1
            claim = InMemoryPerformanceClaim(
                owner=command.owner,
                expires_at=command.claim_expires_at,
                attempt_count=attempt_count,
            )
            claimed = replace(
                item,
                state=PerformanceRecalculationWorkItemState.CLAIMED.value,
                claim=claim,
                attempt_count=attempt_count,
                updated_at=command.claimed_at,
            )
            self._state.performance_recalculation_work_items_by_id[item.id] = claimed
            claimed_items.append(_work_item_to_domain(claimed))

        self._set_batch_running(command.batch_id, command.claimed_at)
        return tuple(claimed_items)

    async def mark_recalculation_work_completed(
        self,
        command: CompleteScorePerformanceRecalculationWork,
    ) -> PerformanceRecalculationWorkItem | None:
        item = self._state.performance_recalculation_work_items_by_id.get(command.work_item_id)
        if item is None:
            return None
        state = PerformanceRecalculationWorkItemState(item.state)
        if state.is_terminal:
            return (
                _work_item_to_domain(item)
                if state is PerformanceRecalculationWorkItemState.COMPLETED
                else None
            )
        if not _has_active_recalculation_work_claim(
            item,
            owner=command.owner,
            at=command.completed_at,
        ):
            return None

        completed = replace(
            item,
            state=PerformanceRecalculationWorkItemState.COMPLETED.value,
            calculation_id=command.calculation_id,
            claim=None,
            updated_at=command.completed_at,
        )
        self._state.performance_recalculation_work_items_by_id[item.id] = completed
        self._refresh_batch_progress(item.batch_id, command.completed_at)
        return _work_item_to_domain(completed)

    async def mark_recalculation_work_unavailable(
        self,
        command: MarkScorePerformanceRecalculationWorkUnavailable,
    ) -> PerformanceRecalculationWorkItem | None:
        item = self._state.performance_recalculation_work_items_by_id.get(command.work_item_id)
        if item is None:
            return None
        state = PerformanceRecalculationWorkItemState(item.state)
        if state.is_terminal:
            return (
                _work_item_to_domain(item)
                if state is PerformanceRecalculationWorkItemState.UNAVAILABLE
                else None
            )
        if not _has_active_recalculation_work_claim(
            item,
            owner=command.owner,
            at=command.completed_at,
        ):
            return None

        unavailable = replace(
            item,
            state=PerformanceRecalculationWorkItemState.UNAVAILABLE.value,
            calculation_id=command.calculation_id,
            claim=None,
            last_error=command.reason,
            updated_at=command.completed_at,
        )
        self._state.performance_recalculation_work_items_by_id[item.id] = unavailable
        self._refresh_batch_progress(item.batch_id, command.completed_at)
        return _work_item_to_domain(unavailable)

    async def mark_recalculation_work_failed(
        self,
        command: MarkScorePerformanceRecalculationWorkFailed,
    ) -> PerformanceRecalculationWorkItem | None:
        item = self._state.performance_recalculation_work_items_by_id.get(command.work_item_id)
        if item is None:
            return None
        if PerformanceRecalculationWorkItemState(item.state).is_terminal:
            return None
        if not _has_active_recalculation_work_claim(
            item,
            owner=command.owner,
            at=command.failed_at,
        ):
            return None

        failed = replace(
            item,
            last_error=command.error,
            updated_at=command.failed_at,
        )
        self._state.performance_recalculation_work_items_by_id[item.id] = failed
        self._set_batch_running(item.batch_id, command.failed_at)
        return _work_item_to_domain(failed)

    async def get_recalculation_batch_by_id(
        self,
        batch_id: int,
    ) -> PerformanceRecalculationBatch | None:
        batch = self._state.performance_recalculation_batches_by_id.get(batch_id)
        return self._batch_to_domain(batch) if batch is not None else None

    async def get_recalculation_work_item_by_id(
        self,
        work_item_id: int,
    ) -> PerformanceRecalculationWorkItem | None:
        item = self._state.performance_recalculation_work_items_by_id.get(work_item_id)
        return _work_item_to_domain(item) if item is not None else None

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
            requires_commit=True,
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

    def _work_items_for_batch(
        self,
        batch_id: int,
    ) -> tuple[InMemoryPerformanceRecalculationWorkItemRecord, ...]:
        item_ids = self._state.performance_recalculation_work_item_ids_by_batch_id.get(
            batch_id,
            [],
        )
        return tuple(
            item
            for item_id in item_ids
            if (item := self._state.performance_recalculation_work_items_by_id.get(item_id))
            is not None
        )

    def _set_batch_running(self, batch_id: int, updated_at: datetime) -> None:
        batch = self._state.performance_recalculation_batches_by_id.get(batch_id)
        if batch is None or batch.status == PerformanceRecalculationBatchStatus.COMPLETED.value:
            return
        self._state.performance_recalculation_batches_by_id[batch_id] = replace(
            batch,
            status=PerformanceRecalculationBatchStatus.RUNNING.value,
            updated_at=updated_at,
        )

    def _refresh_batch_progress(self, batch_id: int, updated_at: datetime) -> None:
        batch = self._state.performance_recalculation_batches_by_id.get(batch_id)
        if batch is None:
            return
        work_items = self._work_items_for_batch(batch_id)
        completed_count = sum(
            item.state == PerformanceRecalculationWorkItemState.COMPLETED.value
            for item in work_items
        )
        unavailable_count = sum(
            item.state == PerformanceRecalculationWorkItemState.UNAVAILABLE.value
            for item in work_items
        )
        terminal_count = completed_count + unavailable_count
        status = (
            PerformanceRecalculationBatchStatus.COMPLETED
            if terminal_count == batch.candidate_count
            else PerformanceRecalculationBatchStatus.RUNNING
        )
        self._state.performance_recalculation_batches_by_id[batch_id] = replace(
            batch,
            status=status.value,
            completed_count=completed_count,
            unavailable_count=unavailable_count,
            updated_at=updated_at,
        )

    def _batch_to_domain(
        self,
        batch: InMemoryPerformanceRecalculationBatchRecord,
    ) -> PerformanceRecalculationBatch:
        return PerformanceRecalculationBatch(
            id=batch.id,
            status=PerformanceRecalculationBatchStatus(batch.status),
            filters=batch.filters,
            reason_counts=batch.reason_counts,
            target_calculator_version=batch.target_calculator_version,
            target_formula_profile=batch.target_formula_profile,
            candidate_count=batch.candidate_count,
            completed_count=batch.completed_count,
            unavailable_count=batch.unavailable_count,
            last_error=self._latest_batch_error(batch.id),
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )

    def _latest_batch_error(self, batch_id: int) -> str | None:
        work_items_with_errors = [
            item for item in self._work_items_for_batch(batch_id) if item.last_error is not None
        ]
        if len(work_items_with_errors) == 0:
            return None
        return max(work_items_with_errors, key=lambda item: (item.updated_at, item.id)).last_error


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


def _is_recalculation_work_claimable(
    item: InMemoryPerformanceRecalculationWorkItemRecord,
    claimed_at: datetime,
) -> bool:
    state = PerformanceRecalculationWorkItemState(item.state)
    if state.is_terminal:
        return False
    if item.claim is not None and item.claim.expires_at > claimed_at:
        return False
    return state in {
        PerformanceRecalculationWorkItemState.PENDING,
        PerformanceRecalculationWorkItemState.CLAIMED,
    }


def _has_active_recalculation_work_claim(
    item: InMemoryPerformanceRecalculationWorkItemRecord,
    *,
    owner: str,
    at: datetime,
) -> bool:
    return (
        item.state == PerformanceRecalculationWorkItemState.CLAIMED.value
        and item.claim is not None
        and item.claim.owner == owner
        and item.claim.expires_at > at
    )


def _work_item_to_domain(
    item: InMemoryPerformanceRecalculationWorkItemRecord,
) -> PerformanceRecalculationWorkItem:
    claim_owner = None if item.claim is None else item.claim.owner
    claim_expires_at = None if item.claim is None else item.claim.expires_at
    return PerformanceRecalculationWorkItem(
        id=item.id,
        batch_id=item.batch_id,
        score_id=item.score_id,
        reason=item.reason,
        state=PerformanceRecalculationWorkItemState(item.state),
        calculation_id=item.calculation_id,
        claim_owner=claim_owner,
        claim_expires_at=claim_expires_at,
        attempt_count=item.attempt_count,
        last_error=item.last_error,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
