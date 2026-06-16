"""Command repository contract tests for score performance persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculation,
    PerformanceCalculationState,
    PerformanceRecalculationBatchStatus,
    PerformanceRecalculationWorkItemState,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    ClaimScorePerformanceCalculation,
    ClaimScorePerformanceRecalculationWork,
    CompleteScorePerformanceCalculation,
    CompleteScorePerformanceRecalculationWork,
    CreateScorePerformanceCalculation,
    CreateScorePerformanceRecalculationBatch,
    CreateScorePerformanceRecalculationWorkItem,
    MarkScorePerformanceCalculationUnavailable,
    MarkScorePerformanceRecalculationWorkFailed,
    MarkScorePerformanceRecalculationWorkUnavailable,
    UpdateScorePerformanceCalculationState,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_NOW = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)


def _memory_factory() -> UnitOfWorkFactory:
    return InMemoryUnitOfWorkFactory()


async def test_duplicate_requests_reuse_one_current_calculation() -> None:
    factory = _memory_factory()

    async with factory() as uow:
        first = await uow.score_performance.create_or_reuse_calculation(
            _request(score_id=10, calculator_version="4.0.2")
        )
        second = await uow.score_performance.create_or_reuse_calculation(
            _request(score_id=10, calculator_version="4.0.2")
        )
        await uow.commit()

    async with factory() as uow:
        current = await uow.score_performance.get_current_for_score(10)

    assert first.created is True
    assert first.is_replacement is False
    assert first.requires_commit is True
    assert second.created is False
    assert second.is_replacement is False
    assert second.requires_commit is False
    assert second.calculation.id == first.calculation.id
    assert current == first.calculation


async def test_claim_conflict_is_retryable_without_marking_unavailable() -> None:
    factory = _memory_factory()
    created_id = await _create_current(factory, score_id=11)

    async with factory() as uow:
        first_claim = await uow.score_performance.claim_pending_calculation(
            _claim(calculation_id=created_id, owner="worker-a", claimed_at=_NOW)
        )
        conflict = await uow.score_performance.claim_pending_calculation(
            _claim(calculation_id=created_id, owner="worker-b", claimed_at=_NOW)
        )
        stale_claim = await uow.score_performance.claim_pending_calculation(
            _claim(
                calculation_id=created_id,
                owner="worker-b",
                claimed_at=_NOW + timedelta(minutes=6),
            )
        )
        current = await uow.score_performance.get_current_for_score(11)
        await uow.commit()

    assert first_claim is not None
    assert first_claim.owner == "worker-a"
    assert first_claim.attempt_count == 1
    assert conflict is None
    assert stale_claim is not None
    assert stale_claim.owner == "worker-b"
    assert stale_claim.attempt_count == 2
    assert current is not None
    assert current.state is PerformanceCalculationState.QUEUED


async def test_pending_calculation_state_transitions_are_durable() -> None:
    factory = _memory_factory()
    created_id = await _create_current(factory, score_id=21)

    async with factory() as uow:
        fetching = await uow.score_performance.update_pending_calculation_state(
            UpdateScorePerformanceCalculationState(
                calculation_id=created_id,
                expected_state=PerformanceCalculationState.QUEUED,
                state=PerformanceCalculationState.FETCHING_FILE,
                transitioned_at=_NOW,
            )
        )
        calculating = await uow.score_performance.update_pending_calculation_state(
            UpdateScorePerformanceCalculationState(
                calculation_id=created_id,
                expected_state=PerformanceCalculationState.FETCHING_FILE,
                state=PerformanceCalculationState.CALCULATING,
                transitioned_at=_NOW + timedelta(seconds=1),
            )
        )
        current = await uow.score_performance.get_current_for_score(21)
        await uow.commit()

    assert fetching is not None
    assert fetching.state is PerformanceCalculationState.FETCHING_FILE
    assert calculating is not None
    assert calculating.state is PerformanceCalculationState.CALCULATING
    assert current == calculating


async def test_pending_calculation_state_transitions_do_not_skip_forward() -> None:
    factory = _memory_factory()
    created_id = await _create_current(factory, score_id=23)

    async with factory() as uow:
        transitioned = await uow.score_performance.update_pending_calculation_state(
            UpdateScorePerformanceCalculationState(
                calculation_id=created_id,
                expected_state=PerformanceCalculationState.FETCHING_FILE,
                state=PerformanceCalculationState.CALCULATING,
                transitioned_at=_NOW,
            )
        )
        current = await uow.score_performance.get_current_for_score(23)
        await uow.commit()

    assert transitioned is None
    assert current is not None
    assert current.state is PerformanceCalculationState.QUEUED


async def test_terminal_calculation_state_does_not_transition_back_to_pending() -> None:
    factory = _memory_factory()
    created_id = await _create_current(factory, score_id=22)
    completed = await _complete(
        factory,
        calculation_id=created_id,
        calculator_version="4.0.2",
    )

    async with factory() as uow:
        transitioned = await uow.score_performance.update_pending_calculation_state(
            UpdateScorePerformanceCalculationState(
                calculation_id=created_id,
                expected_state=PerformanceCalculationState.QUEUED,
                state=PerformanceCalculationState.FETCHING_FILE,
                transitioned_at=_NOW + timedelta(seconds=1),
            )
        )
        current = await uow.score_performance.get_current_for_score(22)
        await uow.commit()

    assert transitioned is None
    assert current == completed


async def test_replacement_preserves_old_current_until_completed_finalization() -> None:
    factory = _memory_factory()
    current_id = await _create_current(factory, score_id=12, calculator_version="4.0.2")
    _ = await _complete(factory, calculation_id=current_id, calculator_version="4.0.2")

    async with factory() as uow:
        replacement = await uow.score_performance.create_or_reuse_calculation(
            _request(score_id=12, calculator_version="4.1.0")
        )
        current_before_finalization = await uow.score_performance.get_current_for_score(12)
        await uow.commit()

    assert replacement.created is True
    assert replacement.is_replacement is True
    assert replacement.requires_commit is True
    assert replacement.calculation.id != current_id
    assert replacement.calculation.is_current is False
    assert current_before_finalization is not None
    assert current_before_finalization.id == current_id
    assert current_before_finalization.is_current is True

    assert replacement.calculation.id is not None
    finalized = await _complete(
        factory,
        calculation_id=replacement.calculation.id,
        calculator_version="4.1.0",
    )

    async with factory() as uow:
        old_current = await uow.score_performance.get_by_id(current_id)
        new_current = await uow.score_performance.get_current_for_score(12)

    assert finalized.is_current is True
    assert old_current is not None
    assert old_current.state is PerformanceCalculationState.SUPERSEDED
    assert old_current.is_current is False
    assert new_current is not None
    assert new_current.id == replacement.calculation.id
    assert new_current.state is PerformanceCalculationState.COMPLETED


async def test_mismatched_pending_replacement_is_superseded_before_new_replacement() -> None:
    factory = _memory_factory()
    current_id = await _create_current(factory, score_id=20, calculator_version="4.0.2")
    _ = await _complete(factory, calculation_id=current_id, calculator_version="4.0.2")

    async with factory() as uow:
        first_replacement = await uow.score_performance.create_or_reuse_calculation(
            _request(score_id=20, calculator_version="4.1.0")
        )
        await uow.commit()

    assert first_replacement.calculation.id is not None
    async with factory() as uow:
        next_replacement = await uow.score_performance.create_or_reuse_calculation(
            _request(score_id=20, calculator_version="4.2.0")
        )
        old_replacement = await uow.score_performance.get_by_id(first_replacement.calculation.id)
        current_before_finalization = await uow.score_performance.get_current_for_score(20)
        old_replacement_claim = await uow.score_performance.claim_pending_calculation(
            _claim(
                calculation_id=first_replacement.calculation.id,
                owner="worker-a",
                claimed_at=_NOW,
            )
        )
        await uow.commit()

    assert next_replacement.created is True
    assert next_replacement.is_replacement is True
    assert next_replacement.requires_commit is True
    assert next_replacement.calculation.id != first_replacement.calculation.id
    assert next_replacement.calculation.state is PerformanceCalculationState.QUEUED
    assert old_replacement is not None
    assert old_replacement.state is PerformanceCalculationState.SUPERSEDED
    assert old_replacement.is_current is False
    assert old_replacement_claim is None
    assert current_before_finalization is not None
    assert current_before_finalization.id == current_id
    assert current_before_finalization.state is PerformanceCalculationState.COMPLETED

    stale_finalize = await _complete_or_none(
        factory,
        calculation_id=first_replacement.calculation.id,
        calculator_version="4.1.0",
    )
    assert stale_finalize is None

    assert next_replacement.calculation.id is not None
    finalized = await _complete(
        factory,
        calculation_id=next_replacement.calculation.id,
        calculator_version="4.2.0",
    )

    async with factory() as uow:
        current_after_finalization = await uow.score_performance.get_current_for_score(20)

    assert finalized.id == next_replacement.calculation.id
    assert current_after_finalization is not None
    assert current_after_finalization.id == next_replacement.calculation.id


async def test_unavailable_replacement_finalization_switches_current_once() -> None:
    factory = _memory_factory()
    current_id = await _create_current(factory, score_id=13, calculator_version="4.0.2")
    _ = await _complete(factory, calculation_id=current_id, calculator_version="4.0.2")

    async with factory() as uow:
        replacement = await uow.score_performance.create_or_reuse_calculation(
            _request(score_id=13, calculator_version="4.1.0")
        )
        await uow.commit()

    assert replacement.calculation.id is not None
    async with factory() as uow:
        unavailable = await uow.score_performance.mark_unavailable(
            MarkScorePerformanceCalculationUnavailable(
                calculation_id=replacement.calculation.id,
                calculator_name="rosu-pp-py",
                calculator_version="4.1.0",
                formula_profile=FormulaProfile.VANILLA_RANKED,
                beatmap_file_attachment_id=None,
                beatmap_file_checksum_md5=None,
                reason="osu_file_unusable",
                calculated_at=_NOW,
            )
        )
        current = await uow.score_performance.get_current_for_score(13)
        old_current = await uow.score_performance.get_by_id(current_id)
        await uow.commit()

    assert unavailable is not None
    assert unavailable.is_current is True
    assert unavailable.state is PerformanceCalculationState.UNAVAILABLE
    assert current == unavailable
    assert old_current is not None
    assert old_current.state is PerformanceCalculationState.SUPERSEDED


async def test_recalculation_batch_creation_preserves_work_set() -> None:
    factory = _memory_factory()

    async with factory() as uow:
        batch = await uow.score_performance.create_recalculation_batch(
            _batch(
                filters={"all": True, "ruleset": "osu"},
                candidates=(
                    _work(score_id=101, reason="uncalculated"),
                    _work(score_id=102, reason="stale"),
                    _work(score_id=103, reason="stale"),
                ),
            )
        )
        await uow.commit()

    async with factory() as uow:
        durable_batch = await uow.score_performance.get_recalculation_batch_by_id(batch.id or 0)
        first_work = await uow.score_performance.get_recalculation_work_item_by_id(1)

    assert batch.id == 1
    assert durable_batch is not None
    assert durable_batch.status is PerformanceRecalculationBatchStatus.PENDING
    assert durable_batch.filters == {"all": True, "ruleset": "osu"}
    assert durable_batch.reason_counts == {"uncalculated": 1, "stale": 2}
    assert durable_batch.target_calculator_version == "4.1.0"
    assert durable_batch.target_formula_profile is FormulaProfile.VANILLA_RANKED
    assert durable_batch.candidate_count == 3
    assert durable_batch.completed_count == 0
    assert durable_batch.unavailable_count == 0
    assert durable_batch.last_error is None
    assert first_work is not None
    assert first_work.batch_id == batch.id
    assert first_work.score_id == 101
    assert first_work.reason == "uncalculated"
    assert first_work.state is PerformanceRecalculationWorkItemState.PENDING


async def test_recalculation_work_claim_is_bounded_and_recovers_stale_claims() -> None:
    factory = _memory_factory()
    batch_id = await _create_recalculation_batch(factory)

    async with factory() as uow:
        first_claim = await uow.score_performance.claim_recalculation_work(
            _work_claim(batch_id=batch_id, owner="worker-a", claimed_at=_NOW, limit=2)
        )
        active_conflict = await uow.score_performance.claim_recalculation_work(
            _work_claim(batch_id=batch_id, owner="worker-b", claimed_at=_NOW, limit=3)
        )
        stale_claim = await uow.score_performance.claim_recalculation_work(
            _work_claim(
                batch_id=batch_id,
                owner="worker-b",
                claimed_at=_NOW + timedelta(minutes=6),
                limit=2,
            )
        )
        await uow.commit()

    assert [item.id for item in first_claim] == [1, 2]
    assert [item.id for item in active_conflict] == [3]
    assert [item.id for item in stale_claim] == [1, 2]
    assert {item.claim_owner for item in stale_claim} == {"worker-b"}
    assert [item.attempt_count for item in stale_claim] == [2, 2]


async def test_stale_recalculation_work_owner_cannot_finalize_after_reclaim() -> None:
    factory = _memory_factory()
    batch_id = await _create_recalculation_batch(factory)

    async with factory() as uow:
        first_claim = await uow.score_performance.claim_recalculation_work(
            _work_claim(batch_id=batch_id, owner="worker-a", claimed_at=_NOW, limit=1)
        )
        stale_claim = await uow.score_performance.claim_recalculation_work(
            _work_claim(
                batch_id=batch_id,
                owner="worker-b",
                claimed_at=_NOW + timedelta(minutes=6),
                limit=1,
            )
        )
        stale_completion = await uow.score_performance.mark_recalculation_work_completed(
            CompleteScorePerformanceRecalculationWork(
                work_item_id=first_claim[0].id or 0,
                owner="worker-a",
                calculation_id=201,
                completed_at=_NOW + timedelta(minutes=6, seconds=30),
            )
        )
        work_item = await uow.score_performance.get_recalculation_work_item_by_id(
            first_claim[0].id or 0
        )
        await uow.commit()

    assert [item.id for item in stale_claim] == [1]
    assert stale_completion is None
    assert work_item is not None
    assert work_item.state is PerformanceRecalculationWorkItemState.CLAIMED
    assert work_item.claim_owner == "worker-b"
    assert work_item.calculation_id is None


async def test_recalculation_work_outcomes_update_batch_progress_and_last_error() -> None:
    factory = _memory_factory()
    batch_id = await _create_recalculation_batch(factory)

    async with factory() as uow:
        claimed = await uow.score_performance.claim_recalculation_work(
            _work_claim(batch_id=batch_id, owner="worker-a", claimed_at=_NOW, limit=3)
        )
        completed = await uow.score_performance.mark_recalculation_work_completed(
            CompleteScorePerformanceRecalculationWork(
                work_item_id=claimed[0].id or 0,
                owner="worker-a",
                calculation_id=201,
                completed_at=_NOW + timedelta(minutes=1),
            )
        )
        unavailable = await uow.score_performance.mark_recalculation_work_unavailable(
            MarkScorePerformanceRecalculationWorkUnavailable(
                work_item_id=claimed[1].id or 0,
                owner="worker-a",
                calculation_id=202,
                reason="osu_file_unusable",
                completed_at=_NOW + timedelta(minutes=2),
            )
        )
        failed = await uow.score_performance.mark_recalculation_work_failed(
            MarkScorePerformanceRecalculationWorkFailed(
                work_item_id=claimed[2].id or 0,
                owner="worker-a",
                error="calculator timeout",
                failed_at=_NOW + timedelta(minutes=3),
            )
        )
        progress = await uow.score_performance.get_recalculation_batch_by_id(batch_id)
        await uow.commit()

    assert completed is not None
    assert completed.state is PerformanceRecalculationWorkItemState.COMPLETED
    assert completed.calculation_id == 201
    assert completed.claim_owner is None
    assert completed.attempt_count == 1
    assert unavailable is not None
    assert unavailable.state is PerformanceRecalculationWorkItemState.UNAVAILABLE
    assert unavailable.calculation_id == 202
    assert unavailable.attempt_count == 1
    assert unavailable.last_error == "osu_file_unusable"
    assert failed is not None
    assert failed.state is PerformanceRecalculationWorkItemState.CLAIMED
    assert failed.claim_owner == "worker-a"
    assert failed.attempt_count == 1
    assert failed.last_error == "calculator timeout"
    assert progress is not None
    assert progress.status is PerformanceRecalculationBatchStatus.RUNNING
    assert progress.completed_count == 1
    assert progress.unavailable_count == 1
    assert progress.last_error == "calculator timeout"

    async with factory() as uow:
        retry = await uow.score_performance.claim_recalculation_work(
            _work_claim(
                batch_id=batch_id,
                owner="worker-b",
                claimed_at=_NOW + timedelta(minutes=6),
                limit=3,
            )
        )
        retry_completed = await uow.score_performance.mark_recalculation_work_completed(
            CompleteScorePerformanceRecalculationWork(
                work_item_id=retry[0].id or 0,
                owner="worker-b",
                calculation_id=203,
                completed_at=_NOW + timedelta(minutes=7),
            )
        )
        finished = await uow.score_performance.get_recalculation_batch_by_id(batch_id)
        await uow.commit()

    assert [item.id for item in retry] == [3]
    assert [item.attempt_count for item in retry] == [2]
    assert retry_completed is not None
    assert retry_completed.attempt_count == 2
    assert finished is not None
    assert finished.status is PerformanceRecalculationBatchStatus.COMPLETED
    assert finished.completed_count == 2
    assert finished.unavailable_count == 1
    assert finished.last_error == "calculator timeout"


async def _create_current(
    factory: UnitOfWorkFactory,
    *,
    score_id: int,
    calculator_version: str = "4.0.2",
) -> int:
    async with factory() as uow:
        result = await uow.score_performance.create_or_reuse_calculation(
            _request(score_id=score_id, calculator_version=calculator_version)
        )
        await uow.commit()
    assert result.calculation.id is not None
    return result.calculation.id


async def _create_recalculation_batch(factory: UnitOfWorkFactory) -> int:
    async with factory() as uow:
        batch = await uow.score_performance.create_recalculation_batch(
            _batch(
                filters={"all": True},
                candidates=(
                    _work(score_id=101, reason="uncalculated"),
                    _work(score_id=102, reason="stale"),
                    _work(score_id=103, reason="formula_profile_mismatch"),
                ),
            )
        )
        await uow.commit()
    assert batch.id is not None
    return batch.id


async def _complete(
    factory: UnitOfWorkFactory,
    *,
    calculation_id: int,
    calculator_version: str,
) -> PerformanceCalculation:
    completed = await _complete_or_none(
        factory,
        calculation_id=calculation_id,
        calculator_version=calculator_version,
    )
    assert completed is not None
    return completed


async def _complete_or_none(
    factory: UnitOfWorkFactory,
    *,
    calculation_id: int,
    calculator_version: str,
) -> PerformanceCalculation | None:
    async with factory() as uow:
        completed = await uow.score_performance.mark_completed(
            CompleteScorePerformanceCalculation(
                calculation_id=calculation_id,
                pp=Decimal("123.456789"),
                star_rating=Decimal("5.43210"),
                calculator_name="rosu-pp-py",
                calculator_version=calculator_version,
                formula_profile=FormulaProfile.VANILLA_RANKED,
                beatmap_file_attachment_id=55,
                beatmap_file_checksum_md5="a" * 32,
                calculated_at=_NOW,
            )
        )
        await uow.commit()
    return completed


def _request(
    *,
    score_id: int,
    calculator_version: str,
) -> CreateScorePerformanceCalculation:
    return CreateScorePerformanceCalculation(
        score_id=score_id,
        calculator_name="rosu-pp-py",
        calculator_version=calculator_version,
        formula_profile=FormulaProfile.VANILLA_RANKED,
        requested_at=_NOW,
    )


def _claim(
    *,
    calculation_id: int,
    owner: str,
    claimed_at: datetime,
) -> ClaimScorePerformanceCalculation:
    return ClaimScorePerformanceCalculation(
        calculation_id=calculation_id,
        owner=owner,
        claimed_at=claimed_at,
        claim_expires_at=claimed_at + timedelta(minutes=5),
    )


def _batch(
    *,
    filters: dict[str, object],
    candidates: tuple[CreateScorePerformanceRecalculationWorkItem, ...],
) -> CreateScorePerformanceRecalculationBatch:
    reason_counts: dict[str, int] = {}
    for candidate in candidates:
        reason_counts[candidate.reason] = reason_counts.get(candidate.reason, 0) + 1
    return CreateScorePerformanceRecalculationBatch(
        filters=filters,
        reason_counts=reason_counts,
        target_calculator_version="4.1.0",
        target_formula_profile=FormulaProfile.VANILLA_RANKED,
        work_items=candidates,
        created_at=_NOW,
    )


def _work(
    *,
    score_id: int,
    reason: str,
) -> CreateScorePerformanceRecalculationWorkItem:
    return CreateScorePerformanceRecalculationWorkItem(
        score_id=score_id,
        reason=reason,
    )


def _work_claim(
    *,
    batch_id: int,
    owner: str,
    claimed_at: datetime,
    limit: int,
) -> ClaimScorePerformanceRecalculationWork:
    return ClaimScorePerformanceRecalculationWork(
        batch_id=batch_id,
        owner=owner,
        claimed_at=claimed_at,
        claim_expires_at=claimed_at + timedelta(minutes=5),
        limit=limit,
    )
