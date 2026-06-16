"""In-memory performance state tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculation,
    PerformanceCalculationState,
)
from osu_server.repositories.memory.commands.state import (
    InMemoryCommandRepositoryState,
    InMemoryPerformanceClaim,
    InMemoryPerformanceRecalculationBatchRecord,
    InMemoryPerformanceRecalculationWorkItemRecord,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

_NOW = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)


def test_performance_state_clone_preserves_rows_batches_work_claims_and_replacements() -> None:
    state = InMemoryCommandRepositoryState()
    current = _calculation(calculation_id=1, score_id=10, is_current=True)
    replacement = _calculation(calculation_id=2, score_id=10, is_current=False)
    claim = InMemoryPerformanceClaim(
        owner="worker-1",
        expires_at=_NOW + timedelta(minutes=5),
        attempt_count=1,
    )
    batch = InMemoryPerformanceRecalculationBatchRecord(
        id=1,
        status="pending",
        filters={"all": True},
        reason_counts={"uncalculated": 1},
        target_calculator_version="4.0.2",
        target_formula_profile=FormulaProfile.VANILLA_RANKED,
        candidate_count=1,
        completed_count=0,
        unavailable_count=0,
        created_at=_NOW,
        updated_at=_NOW,
    )
    work_item = InMemoryPerformanceRecalculationWorkItemRecord(
        id=1,
        batch_id=1,
        score_id=10,
        reason="uncalculated",
        state="pending",
        calculation_id=2,
        claim=claim,
        last_error=None,
        created_at=_NOW,
        updated_at=_NOW,
    )

    state.performance_calculations_by_id[current.id or 0] = current
    state.performance_calculations_by_id[replacement.id or 0] = replacement
    state.current_performance_calculation_id_by_score_id[10] = current.id or 0
    state.replacement_performance_calculation_id_by_score_id[10] = replacement.id or 0
    state.performance_claims_by_calculation_id[current.id or 0] = claim
    state.performance_recalculation_batches_by_id[batch.id] = batch
    state.performance_recalculation_work_items_by_id[work_item.id] = work_item
    state.performance_recalculation_work_item_ids_by_batch_id[batch.id] = [work_item.id]

    clone = state.clone()
    clone.performance_claims_by_calculation_id[current.id or 0] = InMemoryPerformanceClaim(
        owner="worker-2",
        expires_at=_NOW + timedelta(minutes=10),
        attempt_count=2,
    )

    assert clone.performance_calculations_by_id[1] == current
    assert clone.performance_calculations_by_id[2] == replacement
    assert clone.current_performance_calculation_id_by_score_id[10] == 1
    assert clone.replacement_performance_calculation_id_by_score_id[10] == 2
    assert clone.performance_recalculation_batches_by_id[1] == batch
    assert clone.performance_recalculation_work_items_by_id[1] == work_item
    assert clone.performance_recalculation_work_item_ids_by_batch_id[1] == [1]
    assert state.performance_claims_by_calculation_id[1].owner == "worker-1"


def test_unit_of_work_factory_commits_performance_state() -> None:
    factory = InMemoryUnitOfWorkFactory()
    working = factory.snapshot()
    calculation = _calculation(calculation_id=1, score_id=10, is_current=True)
    claim = InMemoryPerformanceClaim(
        owner="worker-1",
        expires_at=_NOW + timedelta(minutes=5),
        attempt_count=1,
    )
    working.performance_calculations_by_id[1] = calculation
    working.current_performance_calculation_id_by_score_id[10] = 1
    working.performance_claims_by_calculation_id[1] = claim

    factory.commit_state(working)
    working.performance_calculations_by_id.clear()
    committed = factory.snapshot()

    assert committed.performance_calculations_by_id[1] == calculation
    assert committed.current_performance_calculation_id_by_score_id[10] == 1
    assert committed.performance_claims_by_calculation_id[1] == claim


def _calculation(
    *,
    calculation_id: int,
    score_id: int,
    is_current: bool,
) -> PerformanceCalculation:
    return PerformanceCalculation(
        id=calculation_id,
        score_id=score_id,
        state=PerformanceCalculationState.QUEUED,
        is_current=is_current,
        pp=None,
        star_rating=None,
        calculator_name="rosu-pp-py",
        calculator_version="4.0.2",
        formula_profile=FormulaProfile.VANILLA_RANKED,
        beatmap_file_attachment_id=None,
        beatmap_file_checksum_md5=None,
        unavailable_reason=None,
        calculated_at=None,
    )
