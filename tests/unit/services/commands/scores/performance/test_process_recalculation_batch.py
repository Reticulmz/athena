"""Tests for durable performance recalculation batch processing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, final

import pytest

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculation,
    PerformanceCalculationState,
    PerformanceRecalculationBatchStatus,
    PerformanceRecalculationWorkItemState,
    RecalculationCandidateReason,
)
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.score_performance import (
    ClaimScorePerformanceRecalculationWork,
    CompleteScorePerformanceCalculation,
    CreateScorePerformanceCalculation,
    CreateScorePerformanceRecalculationBatch,
    CreateScorePerformanceRecalculationWorkItem,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores.performance import (
    PerformanceRuntimeSettings,
    ProcessPerformanceRecalculationBatchCommand,
    ProcessPerformanceRecalculationBatchOutcome,
    ProcessPerformanceRecalculationBatchUseCase,
    RequestPerformanceCalculationCommand,
    RequestPerformanceCalculationOutcome,
    RequestPerformanceCalculationResult,
    RequestPerformanceCalculationUseCase,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_NOW = datetime(2026, 6, 16, 1, 0, 0, tzinfo=UTC)
_CALCULATOR_NAME = "rosu-pp-py"
_CALCULATOR_VERSION = "4.1.0"


@dataclass(frozen=True, slots=True)
class _RecordedRequest:
    score_id: int
    calculator_name: str
    calculator_version: str
    requested_at: datetime


@final
class _CalculatorIdentity:
    def calculator_name(self) -> str:
        return _CALCULATOR_NAME

    def calculator_version(self) -> str:
        return _CALCULATOR_VERSION


@final
class _RequestRecorder:
    def __init__(
        self,
        results_by_score_id: dict[int, RequestPerformanceCalculationResult],
    ) -> None:
        self._results_by_score_id = results_by_score_id
        self.calls: list[_RecordedRequest] = []

    async def execute(
        self,
        command: RequestPerformanceCalculationCommand,
    ) -> RequestPerformanceCalculationResult:
        self.calls.append(
            _RecordedRequest(
                score_id=command.score_id,
                calculator_name=command.calculator_name,
                calculator_version=command.calculator_version,
                requested_at=command.requested_at,
            )
        )
        return self._results_by_score_id[command.score_id]


@pytest.mark.asyncio
async def test_claims_bounded_chunk_and_marks_terminal_request_results() -> None:
    factory = InMemoryUnitOfWorkFactory()
    batch_id = await _create_batch(factory, score_ids=(101, 102, 103))
    request = _RequestRecorder(
        {
            101: _request_result(
                outcome=RequestPerformanceCalculationOutcome.ALREADY_CURRENT,
                score_id=101,
                calculation=_calculation(
                    calculation_id=501,
                    score_id=101,
                    state=PerformanceCalculationState.COMPLETED,
                    unavailable_reason=None,
                ),
            ),
            102: _request_result(
                outcome=RequestPerformanceCalculationOutcome.ALREADY_CURRENT,
                score_id=102,
                calculation=_calculation(
                    calculation_id=502,
                    score_id=102,
                    state=PerformanceCalculationState.UNAVAILABLE,
                    unavailable_reason="calculator_input_invalid",
                ),
            ),
        }
    )
    use_case = _use_case(
        factory,
        request,
        settings=PerformanceRuntimeSettings(
            worker_chunk_size=2,
            claim_timeout=timedelta(minutes=7),
        ),
    )

    result = await use_case.execute(_command(batch_id=batch_id, owner="worker-a"))

    assert result.outcome is ProcessPerformanceRecalculationBatchOutcome.PROCESSED
    assert result.claimed_count == 2
    assert result.completed_count == 1
    assert result.unavailable_count == 1
    assert result.retryable_failure_count == 0
    assert request.calls == [
        _RecordedRequest(101, _CALCULATOR_NAME, _CALCULATOR_VERSION, _NOW),
        _RecordedRequest(102, _CALCULATOR_NAME, _CALCULATOR_VERSION, _NOW),
    ]

    async with factory() as uow:
        completed = await uow.score_performance.get_recalculation_work_item_by_id(1)
        unavailable = await uow.score_performance.get_recalculation_work_item_by_id(2)
        untouched = await uow.score_performance.get_recalculation_work_item_by_id(3)
        progress = await uow.score_performance.get_recalculation_batch_by_id(batch_id)

    assert completed is not None
    assert completed.state is PerformanceRecalculationWorkItemState.COMPLETED
    assert completed.calculation_id == 501
    assert completed.claim_owner is None
    assert completed.attempt_count == 1
    assert unavailable is not None
    assert unavailable.state is PerformanceRecalculationWorkItemState.UNAVAILABLE
    assert unavailable.calculation_id == 502
    assert unavailable.last_error == "calculator_input_invalid"
    assert untouched is not None
    assert untouched.state is PerformanceRecalculationWorkItemState.PENDING
    assert progress is not None
    assert progress.status is PerformanceRecalculationBatchStatus.RUNNING
    assert progress.completed_count == 1
    assert progress.unavailable_count == 1


@pytest.mark.asyncio
async def test_pending_or_temporary_conflict_request_results_are_retryable_failures() -> None:
    factory = InMemoryUnitOfWorkFactory()
    batch_id = await _create_batch(factory, score_ids=(101, 102))
    request = _RequestRecorder(
        {
            101: _request_result(
                outcome=RequestPerformanceCalculationOutcome.CREATED_REPLACEMENT,
                score_id=101,
                calculation=_calculation(
                    calculation_id=601,
                    score_id=101,
                    state=PerformanceCalculationState.QUEUED,
                    unavailable_reason=None,
                ),
                created=True,
                is_replacement=True,
            ),
            102: _request_result(
                outcome=RequestPerformanceCalculationOutcome.TEMPORARY_CONFLICT,
                score_id=102,
                calculation=None,
            ),
        }
    )
    claim_timeout = timedelta(minutes=7)
    use_case = _use_case(
        factory,
        request,
        settings=PerformanceRuntimeSettings(claim_timeout=claim_timeout),
    )

    result = await use_case.execute(_command(batch_id=batch_id, owner="worker-a"))

    assert result.outcome is ProcessPerformanceRecalculationBatchOutcome.PROCESSED
    assert result.completed_count == 0
    assert result.unavailable_count == 0
    assert result.retryable_failure_count == 2

    async with factory() as uow:
        pending_replacement = await uow.score_performance.get_recalculation_work_item_by_id(1)
        conflict = await uow.score_performance.get_recalculation_work_item_by_id(2)
        progress = await uow.score_performance.get_recalculation_batch_by_id(batch_id)

    assert pending_replacement is not None
    assert pending_replacement.state is PerformanceRecalculationWorkItemState.CLAIMED
    assert pending_replacement.calculation_id is None
    assert pending_replacement.claim_owner == "worker-a"
    assert pending_replacement.claim_expires_at == _NOW + claim_timeout
    assert pending_replacement.last_error == "replacement_calculation_pending"
    assert conflict is not None
    assert conflict.state is PerformanceRecalculationWorkItemState.CLAIMED
    assert conflict.calculation_id is None
    assert conflict.claim_owner == "worker-a"
    assert conflict.claim_expires_at == _NOW + claim_timeout
    assert conflict.last_error == "temporary_conflict"
    assert progress is not None
    assert progress.unavailable_count == 0
    assert progress.completed_count == 0
    assert progress.last_error == "temporary_conflict"


@pytest.mark.asyncio
async def test_retryable_failures_do_not_starve_later_work_items() -> None:
    factory = InMemoryUnitOfWorkFactory()
    batch_id = await _create_batch(factory, score_ids=(101, 102, 103))
    request = _RequestRecorder(
        {
            101: _request_result(
                outcome=RequestPerformanceCalculationOutcome.CREATED_REPLACEMENT,
                score_id=101,
                calculation=_calculation(
                    calculation_id=601,
                    score_id=101,
                    state=PerformanceCalculationState.QUEUED,
                    unavailable_reason=None,
                ),
                created=True,
                is_replacement=True,
            ),
            102: _request_result(
                outcome=RequestPerformanceCalculationOutcome.CREATED_REPLACEMENT,
                score_id=102,
                calculation=_calculation(
                    calculation_id=602,
                    score_id=102,
                    state=PerformanceCalculationState.QUEUED,
                    unavailable_reason=None,
                ),
                created=True,
                is_replacement=True,
            ),
            103: _request_result(
                outcome=RequestPerformanceCalculationOutcome.ALREADY_CURRENT,
                score_id=103,
                calculation=_calculation(
                    calculation_id=603,
                    score_id=103,
                    state=PerformanceCalculationState.COMPLETED,
                    unavailable_reason=None,
                ),
            ),
        }
    )
    use_case = _use_case(
        factory,
        request,
        settings=PerformanceRuntimeSettings(
            worker_chunk_size=2,
            claim_timeout=timedelta(minutes=7),
        ),
    )

    first = await use_case.execute(_command(batch_id=batch_id, owner="worker-a"))
    second = await use_case.execute(
        _command(
            batch_id=batch_id,
            owner="worker-b",
            claimed_at=_NOW + timedelta(seconds=1),
        )
    )

    assert first.retryable_failure_count == 2
    assert second.claimed_count == 1
    assert second.completed_count == 1
    assert request.calls == [
        _RecordedRequest(101, _CALCULATOR_NAME, _CALCULATOR_VERSION, _NOW),
        _RecordedRequest(102, _CALCULATOR_NAME, _CALCULATOR_VERSION, _NOW),
        _RecordedRequest(
            103,
            _CALCULATOR_NAME,
            _CALCULATOR_VERSION,
            _NOW + timedelta(seconds=1),
        ),
    ]
    async with factory() as uow:
        first_work = await uow.score_performance.get_recalculation_work_item_by_id(1)
        second_work = await uow.score_performance.get_recalculation_work_item_by_id(2)
        third_work = await uow.score_performance.get_recalculation_work_item_by_id(3)

    assert first_work is not None
    assert first_work.state is PerformanceRecalculationWorkItemState.CLAIMED
    assert second_work is not None
    assert second_work.state is PerformanceRecalculationWorkItemState.CLAIMED
    assert third_work is not None
    assert third_work.state is PerformanceRecalculationWorkItemState.COMPLETED


@pytest.mark.asyncio
async def test_stale_claimed_work_is_reclaimed_by_later_processor() -> None:
    factory = InMemoryUnitOfWorkFactory()
    batch_id = await _create_batch(factory, score_ids=(101,))
    claim_timeout = timedelta(minutes=5)
    async with factory() as uow:
        claimed = await uow.score_performance.claim_recalculation_work(
            ClaimScorePerformanceRecalculationWork(
                batch_id=batch_id,
                owner="worker-a",
                claimed_at=_NOW,
                claim_expires_at=_NOW + claim_timeout,
                limit=1,
            )
        )
        await uow.commit()
    assert [item.id for item in claimed] == [1]

    request = _RequestRecorder(
        {
            101: _request_result(
                outcome=RequestPerformanceCalculationOutcome.ALREADY_CURRENT,
                score_id=101,
                calculation=_calculation(
                    calculation_id=701,
                    score_id=101,
                    state=PerformanceCalculationState.COMPLETED,
                    unavailable_reason=None,
                ),
            ),
        }
    )
    use_case = _use_case(
        factory,
        request,
        settings=PerformanceRuntimeSettings(claim_timeout=claim_timeout),
    )

    result = await use_case.execute(
        _command(
            batch_id=batch_id,
            owner="worker-b",
            claimed_at=_NOW + claim_timeout + timedelta(seconds=1),
        )
    )

    assert result.claimed_count == 1
    assert result.completed_count == 1
    reclaim_at = _NOW + claim_timeout + timedelta(seconds=1)
    assert request.calls == [
        _RecordedRequest(101, _CALCULATOR_NAME, _CALCULATOR_VERSION, reclaim_at)
    ]
    async with factory() as uow:
        work_item = await uow.score_performance.get_recalculation_work_item_by_id(1)
        progress = await uow.score_performance.get_recalculation_batch_by_id(batch_id)

    assert work_item is not None
    assert work_item.state is PerformanceRecalculationWorkItemState.COMPLETED
    assert work_item.claim_owner is None
    assert work_item.attempt_count == 2
    assert progress is not None
    assert progress.status is PerformanceRecalculationBatchStatus.COMPLETED
    assert progress.completed_count == 1


@pytest.mark.asyncio
async def test_replacement_request_keeps_old_current_until_terminal_finalization() -> None:
    factory = InMemoryUnitOfWorkFactory()
    score_id = await _persist_score(factory, _score())
    old_current_id = await _create_completed_current(
        factory,
        score_id=score_id,
        calculator_version="4.0.2",
    )
    batch_id = await _create_batch(factory, score_ids=(score_id,))
    request_use_case = RequestPerformanceCalculationUseCase(unit_of_work_factory=factory)
    use_case = ProcessPerformanceRecalculationBatchUseCase(
        unit_of_work_factory=factory,
        request_use_case=request_use_case,
        calculator_identity=_CalculatorIdentity(),
        settings=PerformanceRuntimeSettings(claim_timeout=timedelta(minutes=5)),
    )

    first = await use_case.execute(_command(batch_id=batch_id, owner="worker-a"))

    assert first.retryable_failure_count == 1
    async with factory() as uow:
        current = await uow.score_performance.get_current_for_score(score_id)
        work_item = await uow.score_performance.get_recalculation_work_item_by_id(1)
    assert current is not None
    assert current.id == old_current_id
    assert current.state is PerformanceCalculationState.COMPLETED
    assert work_item is not None
    assert work_item.state is PerformanceRecalculationWorkItemState.CLAIMED
    assert work_item.last_error == "replacement_calculation_pending"

    replacement_id = factory.snapshot().replacement_performance_calculation_id_by_score_id[
        score_id
    ]
    await _complete_calculation(factory, calculation_id=replacement_id)

    second = await use_case.execute(
        _command(
            batch_id=batch_id,
            owner="worker-b",
            claimed_at=_NOW + timedelta(minutes=5, seconds=1),
        )
    )

    assert second.completed_count == 1
    async with factory() as uow:
        final_current = await uow.score_performance.get_current_for_score(score_id)
        final_work_item = await uow.score_performance.get_recalculation_work_item_by_id(1)
        old_current = await uow.score_performance.get_by_id(old_current_id)

    assert final_current is not None
    assert final_current.id == replacement_id
    assert final_current.state is PerformanceCalculationState.COMPLETED
    assert old_current is not None
    assert old_current.state is PerformanceCalculationState.SUPERSEDED
    assert final_work_item is not None
    assert final_work_item.state is PerformanceRecalculationWorkItemState.COMPLETED
    assert final_work_item.calculation_id == replacement_id


def _use_case(
    factory: UnitOfWorkFactory,
    request: _RequestRecorder,
    *,
    settings: PerformanceRuntimeSettings | None = None,
) -> ProcessPerformanceRecalculationBatchUseCase:
    return ProcessPerformanceRecalculationBatchUseCase(
        unit_of_work_factory=factory,
        request_use_case=request,
        calculator_identity=_CalculatorIdentity(),
        settings=settings,
    )


def _command(
    *,
    batch_id: int,
    owner: str,
    claimed_at: datetime = _NOW,
) -> ProcessPerformanceRecalculationBatchCommand:
    return ProcessPerformanceRecalculationBatchCommand(
        batch_id=batch_id,
        claim_owner=owner,
        claimed_at=claimed_at,
    )


async def _create_batch(factory: UnitOfWorkFactory, *, score_ids: tuple[int, ...]) -> int:
    async with factory() as uow:
        batch = await uow.score_performance.create_recalculation_batch(
            CreateScorePerformanceRecalculationBatch(
                filters={"all": True},
                reason_counts={RecalculationCandidateReason.STALE: len(score_ids)},
                target_calculator_version=_CALCULATOR_VERSION,
                target_formula_profile=FormulaProfile.VANILLA_RANKED,
                work_items=tuple(
                    CreateScorePerformanceRecalculationWorkItem(
                        score_id=score_id,
                        reason=RecalculationCandidateReason.STALE,
                    )
                    for score_id in score_ids
                ),
                created_at=_NOW,
            )
        )
        await uow.commit()
    assert batch.id is not None
    return batch.id


async def _persist_score(factory: UnitOfWorkFactory, score: Score) -> int:
    async with factory() as uow:
        created = await uow.scores.create(score)
        await uow.commit()
    assert created.id is not None
    return created.id


async def _create_completed_current(
    factory: UnitOfWorkFactory,
    *,
    score_id: int,
    calculator_version: str,
) -> int:
    async with factory() as uow:
        result = await uow.score_performance.create_or_reuse_calculation(
            request_calculation_command(score_id=score_id, calculator_version=calculator_version)
        )
        await uow.commit()
    calculation_id = _require_calculation_id(result.calculation)
    await _complete_calculation(
        factory,
        calculation_id=calculation_id,
        calculator_version=calculator_version,
    )
    return calculation_id


def request_calculation_command(
    *,
    score_id: int,
    calculator_version: str,
) -> CreateScorePerformanceCalculation:
    return CreateScorePerformanceCalculation(
        score_id=score_id,
        calculator_name=_CALCULATOR_NAME,
        calculator_version=calculator_version,
        formula_profile=FormulaProfile.VANILLA_RANKED,
        requested_at=_NOW,
    )


async def _complete_calculation(
    factory: UnitOfWorkFactory,
    *,
    calculation_id: int,
    calculator_version: str = _CALCULATOR_VERSION,
) -> None:
    async with factory() as uow:
        _ = await uow.score_performance.mark_completed(
            CompleteScorePerformanceCalculation(
                calculation_id=calculation_id,
                pp=Decimal("123.456789"),
                star_rating=Decimal("5.43210"),
                calculator_name=_CALCULATOR_NAME,
                calculator_version=calculator_version,
                formula_profile=FormulaProfile.VANILLA_RANKED,
                beatmap_file_attachment_id=55,
                beatmap_file_checksum_md5="a" * 32,
                calculated_at=_NOW,
            )
        )
        await uow.commit()


def _request_result(
    *,
    outcome: RequestPerformanceCalculationOutcome,
    score_id: int,
    calculation: PerformanceCalculation | None,
    created: bool = False,
    is_replacement: bool = False,
) -> RequestPerformanceCalculationResult:
    return RequestPerformanceCalculationResult(
        outcome=outcome,
        score_id=score_id,
        calculation=calculation,
        created=created,
        is_replacement=is_replacement,
    )


def _calculation(
    *,
    calculation_id: int,
    score_id: int,
    state: PerformanceCalculationState,
    unavailable_reason: str | None,
) -> PerformanceCalculation:
    return PerformanceCalculation(
        id=calculation_id,
        score_id=score_id,
        state=state,
        is_current=True,
        pp=Decimal("123.456789") if state is PerformanceCalculationState.COMPLETED else None,
        star_rating=Decimal("5.43210") if state is PerformanceCalculationState.COMPLETED else None,
        calculator_name=_CALCULATOR_NAME,
        calculator_version=_CALCULATOR_VERSION,
        formula_profile=FormulaProfile.VANILLA_RANKED,
        beatmap_file_attachment_id=55 if state.is_terminal else None,
        beatmap_file_checksum_md5="a" * 32 if state.is_terminal else None,
        unavailable_reason=unavailable_reason,
        calculated_at=_NOW if state.is_terminal else None,
    )


def _score() -> Score:
    return Score(
        id=None,
        user_id=1000,
        beatmap_id=2000,
        beatmap_checksum="0123456789abcdef0123456789abcdef",
        online_checksum="abcdef0123456789abcdef0123456789",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=300,
        n100=50,
        n50=10,
        geki=0,
        katu=0,
        miss=5,
        score=500000,
        max_combo=350,
        accuracy=0.95,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="b20250101",
        submitted_at=_NOW,
        beatmap_status_at_submission=BeatmapRankStatus.RANKED,
    )


def _require_calculation_id(calculation: PerformanceCalculation) -> int:
    if calculation.id is None:
        msg = "calculation id must be assigned"
        raise AssertionError(msg)
    return calculation.id
