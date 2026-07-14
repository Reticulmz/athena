"""Integration-style recovery tests for performance recalculation."""

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
    PerformanceRecalculationBatch,
    PerformanceRecalculationBatchStatus,
    PerformanceRecalculationWorkItemState,
    RecalculationCandidateReason,
)
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.score_performance import (
    CompleteScorePerformanceCalculation,
    CreateScorePerformanceCalculation,
)
from osu_server.repositories.memory.queries.score_performance import (
    InMemoryScorePerformanceQueryRepository,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores.performance import (
    CreatePerformanceRecalculationBatchCommand,
    CreatePerformanceRecalculationBatchMode,
    CreatePerformanceRecalculationBatchOutcome,
    CreatePerformanceRecalculationBatchUseCase,
    PerformanceRuntimeSettings,
    ProcessPerformanceRecalculationBatchCommand,
    ProcessPerformanceRecalculationBatchOutcome,
    ProcessPerformanceRecalculationBatchUseCase,
    RequestPerformanceCalculationUseCase,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_NOW = datetime(2026, 6, 16, 1, 0, 0, tzinfo=UTC)
_CLAIM_TIMEOUT = timedelta(minutes=5)
_CALCULATOR_NAME = "rosu-pp-py"
_ACTIVE_CALCULATOR_VERSION = "4.1.0"
_OLD_CALCULATOR_VERSION = "4.0.2"


@dataclass(frozen=True, slots=True)
class _WakeCall:
    batch_id: int


@dataclass(frozen=True, slots=True)
class _SeededCandidates:
    version_mismatch_score_id: int
    profile_mismatch_score_id: int
    old_version_current_id: int
    old_profile_current_id: int


@dataclass(frozen=True, slots=True)
class _WorkRecoveryExpectation:
    score_id: int
    old_current_id: int
    work_item_id: int
    first_owner: str
    recovery_owner: str
    first_claim_at: datetime


@final
class _CalculatorIdentity:
    def calculator_name(self) -> str:
        return _CALCULATOR_NAME

    def calculator_version(self) -> str:
        return _ACTIVE_CALCULATOR_VERSION


@final
class _WakeRecorder:
    def __init__(self) -> None:
        self.calls: list[_WakeCall] = []

    async def wake_recalculation_batch(self, *, batch_id: int) -> None:
        self.calls.append(_WakeCall(batch_id=batch_id))


@pytest.mark.asyncio
async def test_profile_migration_batch_recovers_after_lost_wake_and_stale_claim() -> None:
    factory = InMemoryUnitOfWorkFactory()
    wake = _WakeRecorder()
    seeded = await _seed_mismatch_candidates(factory)

    batch_id = await _create_profile_migration_batch(factory, wake)
    await _assert_initial_batch(factory, batch_id=batch_id, seeded=seeded)

    processor = _processor(factory)
    version_replacement_id = await _process_stale_recovered_work(
        factory,
        processor,
        batch_id=batch_id,
        expectation=_WorkRecoveryExpectation(
            score_id=seeded.version_mismatch_score_id,
            old_current_id=seeded.old_version_current_id,
            work_item_id=1,
            first_owner="worker-a",
            recovery_owner="worker-b",
            first_claim_at=_NOW + timedelta(minutes=1),
        ),
    )
    profile_replacement_id = await _process_stale_recovered_work(
        factory,
        processor,
        batch_id=batch_id,
        expectation=_WorkRecoveryExpectation(
            score_id=seeded.profile_mismatch_score_id,
            old_current_id=seeded.old_profile_current_id,
            work_item_id=2,
            first_owner="worker-c",
            recovery_owner="worker-d",
            first_claim_at=_NOW + timedelta(minutes=7),
        ),
    )
    await _assert_final_batch(
        factory,
        batch_id=batch_id,
        seeded=seeded,
        version_replacement_id=version_replacement_id,
        profile_replacement_id=profile_replacement_id,
    )


async def _seed_mismatch_candidates(
    factory: UnitOfWorkFactory,
) -> _SeededCandidates:
    version_mismatch_score_id = await _persist_score(
        factory,
        _score(online_checksum="a" * 32),
    )
    profile_mismatch_score_id = await _persist_score(
        factory,
        _score(online_checksum="b" * 32),
    )
    old_version_current_id = await _create_completed_current(
        factory,
        score_id=version_mismatch_score_id,
        calculator_version=_OLD_CALCULATOR_VERSION,
        formula_profile=FormulaProfile.VANILLA_RANKED,
    )
    old_profile_current_id = await _create_completed_current(
        factory,
        score_id=profile_mismatch_score_id,
        calculator_version=_ACTIVE_CALCULATOR_VERSION,
        formula_profile=FormulaProfile.LEGACY_VANILLA_RANKED,
    )
    return _SeededCandidates(
        version_mismatch_score_id=version_mismatch_score_id,
        profile_mismatch_score_id=profile_mismatch_score_id,
        old_version_current_id=old_version_current_id,
        old_profile_current_id=old_profile_current_id,
    )


async def _create_profile_migration_batch(
    factory: InMemoryUnitOfWorkFactory,
    wake: _WakeRecorder,
) -> int:
    create_use_case = CreatePerformanceRecalculationBatchUseCase(
        query_repository=InMemoryScorePerformanceQueryRepository(factory),
        unit_of_work_factory=factory,
        calculator_identity=_CalculatorIdentity(),
        worker_wake=wake,
    )
    created = await create_use_case.execute(
        CreatePerformanceRecalculationBatchCommand(
            mode=CreatePerformanceRecalculationBatchMode.EXECUTE,
            score_id=None,
            beatmap_id=None,
            user_id=None,
            ruleset=None,
            limit=None,
            full_scope=True,
            include_unavailable=False,
            requested_at=_NOW,
        )
    )
    assert created.outcome is CreatePerformanceRecalculationBatchOutcome.CREATED
    assert created.candidate_count == 2
    assert created.reason_counts == {
        RecalculationCandidateReason.CALCULATOR_VERSION_MISMATCH: 1,
        RecalculationCandidateReason.FORMULA_PROFILE_MISMATCH: 1,
    }
    batch_id = _require_batch_id(created.batch)
    assert wake.calls == [_WakeCall(batch_id=batch_id)]
    return batch_id


async def _assert_initial_batch(
    factory: UnitOfWorkFactory,
    *,
    batch_id: int,
    seeded: _SeededCandidates,
) -> None:
    async with factory() as uow:
        batch = await uow.score_performance.get_recalculation_batch_by_id(batch_id)
        first_work = await uow.score_performance.get_recalculation_work_item_by_id(1)
        second_work = await uow.score_performance.get_recalculation_work_item_by_id(2)

    assert batch is not None
    assert batch.status is PerformanceRecalculationBatchStatus.PENDING
    assert batch.target_calculator_version == _ACTIVE_CALCULATOR_VERSION
    assert batch.target_formula_profile is FormulaProfile.VANILLA_RANKED
    assert first_work is not None
    assert first_work.score_id == seeded.version_mismatch_score_id
    assert first_work.reason is RecalculationCandidateReason.CALCULATOR_VERSION_MISMATCH
    assert first_work.state is PerformanceRecalculationWorkItemState.PENDING
    assert second_work is not None
    assert second_work.score_id == seeded.profile_mismatch_score_id
    assert second_work.reason is RecalculationCandidateReason.FORMULA_PROFILE_MISMATCH
    assert second_work.state is PerformanceRecalculationWorkItemState.PENDING


def _processor(factory: UnitOfWorkFactory) -> ProcessPerformanceRecalculationBatchUseCase:
    return ProcessPerformanceRecalculationBatchUseCase(
        unit_of_work_factory=factory,
        request_use_case=RequestPerformanceCalculationUseCase(unit_of_work_factory=factory),
        calculator_identity=_CalculatorIdentity(),
        settings=PerformanceRuntimeSettings(
            worker_chunk_size=1,
            claim_timeout=_CLAIM_TIMEOUT,
        ),
    )


async def _process_stale_recovered_work(
    factory: InMemoryUnitOfWorkFactory,
    processor: ProcessPerformanceRecalculationBatchUseCase,
    *,
    batch_id: int,
    expectation: _WorkRecoveryExpectation,
) -> int:
    first = await processor.execute(
        _process_command(
            batch_id=batch_id,
            owner=expectation.first_owner,
            claimed_at=expectation.first_claim_at,
        )
    )
    assert first.outcome is ProcessPerformanceRecalculationBatchOutcome.PROCESSED
    assert first.claimed_count == 1
    assert first.retryable_failure_count == 1
    replacement_id = _replacement_id_for_score(factory, expectation.score_id)
    await _assert_pending_replacement(factory, expectation=expectation)
    await _complete_calculation(
        factory,
        calculation_id=replacement_id,
        calculator_version=_ACTIVE_CALCULATOR_VERSION,
        formula_profile=FormulaProfile.VANILLA_RANKED,
    )

    second = await processor.execute(
        _process_command(
            batch_id=batch_id,
            owner=expectation.recovery_owner,
            claimed_at=expectation.first_claim_at + _CLAIM_TIMEOUT + timedelta(seconds=1),
        )
    )
    assert second.claimed_count == 1
    assert second.completed_count == 1
    await _assert_completed_replacement(
        factory,
        expectation=expectation,
        replacement_id=replacement_id,
    )
    return replacement_id


async def _assert_pending_replacement(
    factory: UnitOfWorkFactory,
    *,
    expectation: _WorkRecoveryExpectation,
) -> None:
    async with factory() as uow:
        current = await uow.score_performance.get_current_for_score(expectation.score_id)
        work = await uow.score_performance.get_recalculation_work_item_by_id(
            expectation.work_item_id
        )

    assert current is not None
    assert current.id == expectation.old_current_id
    assert work is not None
    assert work.state is PerformanceRecalculationWorkItemState.CLAIMED
    assert work.claim_owner == expectation.first_owner
    assert work.last_error == "replacement_calculation_pending"


async def _assert_completed_replacement(
    factory: UnitOfWorkFactory,
    *,
    expectation: _WorkRecoveryExpectation,
    replacement_id: int,
) -> None:
    async with factory() as uow:
        current = await uow.score_performance.get_current_for_score(expectation.score_id)
        old_current = await uow.score_performance.get_by_id(expectation.old_current_id)
        work = await uow.score_performance.get_recalculation_work_item_by_id(
            expectation.work_item_id
        )

    assert current is not None
    assert current.id == replacement_id
    assert old_current is not None
    assert old_current.state is PerformanceCalculationState.SUPERSEDED
    assert work is not None
    assert work.state is PerformanceRecalculationWorkItemState.COMPLETED
    assert work.calculation_id == replacement_id


async def _assert_final_batch(
    factory: UnitOfWorkFactory,
    *,
    batch_id: int,
    seeded: _SeededCandidates,
    version_replacement_id: int,
    profile_replacement_id: int,
) -> None:
    async with factory() as uow:
        final_batch = await uow.score_performance.get_recalculation_batch_by_id(batch_id)
        version_current = await uow.score_performance.get_current_for_score(
            seeded.version_mismatch_score_id
        )
        profile_current = await uow.score_performance.get_current_for_score(
            seeded.profile_mismatch_score_id
        )

    assert final_batch is not None
    assert final_batch.status is PerformanceRecalculationBatchStatus.COMPLETED
    assert final_batch.completed_count == 2
    assert final_batch.unavailable_count == 0
    assert version_current is not None
    assert version_current.id == version_replacement_id
    assert profile_current is not None
    assert profile_current.id == profile_replacement_id
    assert profile_current.formula_profile is FormulaProfile.VANILLA_RANKED


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
    formula_profile: FormulaProfile,
) -> int:
    async with factory() as uow:
        result = await uow.score_performance.create_or_reuse_calculation(
            CreateScorePerformanceCalculation(
                score_id=score_id,
                calculator_name=_CALCULATOR_NAME,
                calculator_version=calculator_version,
                formula_profile=formula_profile,
                requested_at=_NOW,
            )
        )
        await uow.commit()
    calculation_id = _require_calculation_id(result.calculation)
    await _complete_calculation(
        factory,
        calculation_id=calculation_id,
        calculator_version=calculator_version,
        formula_profile=formula_profile,
    )
    return calculation_id


async def _complete_calculation(
    factory: UnitOfWorkFactory,
    *,
    calculation_id: int,
    calculator_version: str,
    formula_profile: FormulaProfile,
) -> None:
    async with factory() as uow:
        _ = await uow.score_performance.mark_completed(
            CompleteScorePerformanceCalculation(
                calculation_id=calculation_id,
                pp=Decimal("123.456789"),
                star_rating=Decimal("5.43210"),
                calculator_name=_CALCULATOR_NAME,
                calculator_version=calculator_version,
                formula_profile=formula_profile,
                beatmap_file_attachment_id=55,
                beatmap_file_checksum_md5="a" * 32,
                calculated_at=_NOW,
            )
        )
        await uow.commit()


def _process_command(
    *,
    batch_id: int,
    owner: str,
    claimed_at: datetime,
) -> ProcessPerformanceRecalculationBatchCommand:
    return ProcessPerformanceRecalculationBatchCommand(
        batch_id=batch_id,
        claim_owner=owner,
        claimed_at=claimed_at,
    )


def _replacement_id_for_score(factory: InMemoryUnitOfWorkFactory, score_id: int) -> int:
    return factory.snapshot().replacement_performance_calculation_id_by_score_id[score_id]


def _score(*, online_checksum: str) -> Score:
    return Score(
        id=None,
        user_id=1000,
        beatmap_id=2000,
        beatmap_checksum="0123456789abcdef0123456789abcdef",
        online_checksum=online_checksum,
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


def _require_batch_id(batch: PerformanceRecalculationBatch | None) -> int:
    if batch is None or batch.id is None:
        msg = "batch id must be assigned"
        raise AssertionError(msg)
    return batch.id


def _require_calculation_id(calculation: PerformanceCalculation) -> int:
    if calculation.id is None:
        msg = "calculation id must be assigned"
        raise AssertionError(msg)
    return calculation.id
