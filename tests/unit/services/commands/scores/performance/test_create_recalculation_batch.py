"""Tests for creating score performance recalculation batches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, final

import pytest

from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceRecalculationBatch,
    PerformanceRecalculationBatchStatus,
    RecalculationCandidateReason,
)
from osu_server.domain.scores.score import Ruleset
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceCandidateSelection,
    ScorePerformanceRecalculationCandidate,
    ScorePerformanceRecalculationCandidateResult,
)
from osu_server.services.commands.scores.performance import (
    CreatePerformanceRecalculationBatchCommand,
    CreatePerformanceRecalculationBatchMode,
    CreatePerformanceRecalculationBatchOutcome,
    CreatePerformanceRecalculationBatchUseCase,
)

if TYPE_CHECKING:
    from types import TracebackType

    from osu_server.domain.scores.performance import PerformanceCalculation
    from osu_server.repositories.interfaces.commands.score_performance import (
        CreateScorePerformanceRecalculationBatch,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_NOW = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)
_CALCULATOR_NAME = "rosu-pp-py"
_CALCULATOR_VERSION = "4.0.2"


@dataclass(frozen=True, slots=True)
class _WakeCall:
    batch_id: int
    commit_count_at_call: int


@final
class _CalculatorIdentity:
    def calculator_name(self) -> str:
        return _CALCULATOR_NAME

    def calculator_version(self) -> str:
        return _CALCULATOR_VERSION


@final
class _QueryRepository:
    def __init__(self, result: ScorePerformanceRecalculationCandidateResult) -> None:
        self._result = result
        self.selections: list[ScorePerformanceCandidateSelection] = []

    async def select_recalculation_candidates(
        self,
        selection: ScorePerformanceCandidateSelection,
    ) -> ScorePerformanceRecalculationCandidateResult:
        self.selections.append(selection)
        return self._result

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        _ = score_id
        return None


@final
class _UnitOfWorkFactory:
    def __init__(self) -> None:
        self.open_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.created_batches: list[CreateScorePerformanceRecalculationBatch] = []

    def __call__(self) -> _UnitOfWork:
        self.open_count += 1
        return _UnitOfWork(self)


@final
class _UnitOfWork:
    def __init__(self, factory: _UnitOfWorkFactory) -> None:
        self._factory = factory
        self._committed = False
        self.score_performance = _ScorePerformanceCommandRepository(factory)

    async def __aenter__(self) -> _UnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None or not self._committed:
            await self.rollback()

    async def commit(self) -> None:
        self._factory.commit_count += 1
        self._committed = True

    async def rollback(self) -> None:
        self._factory.rollback_count += 1
        self._committed = False


@final
class _ScorePerformanceCommandRepository:
    def __init__(self, factory: _UnitOfWorkFactory) -> None:
        self._factory = factory

    async def create_recalculation_batch(
        self,
        command: CreateScorePerformanceRecalculationBatch,
    ) -> PerformanceRecalculationBatch:
        self._factory.created_batches.append(command)
        batch_id = len(self._factory.created_batches)
        return PerformanceRecalculationBatch(
            id=batch_id,
            status=PerformanceRecalculationBatchStatus.PENDING,
            filters=command.filters,
            reason_counts=command.reason_counts,
            target_calculator_version=command.target_calculator_version,
            target_formula_profile=command.target_formula_profile,
            candidate_count=len(command.work_items),
            completed_count=0,
            unavailable_count=0,
            last_error=None,
            created_at=command.created_at,
            updated_at=command.created_at,
        )


@final
class _WakeRecorder:
    def __init__(self, factory: _UnitOfWorkFactory) -> None:
        self._factory = factory
        self.calls: list[_WakeCall] = []

    async def wake_recalculation_batch(self, *, batch_id: int) -> None:
        self.calls.append(
            _WakeCall(
                batch_id=batch_id,
                commit_count_at_call=self._factory.commit_count,
            )
        )


def _candidate_result(
    *candidates: ScorePerformanceRecalculationCandidate,
) -> ScorePerformanceRecalculationCandidateResult:
    reason_counts: dict[RecalculationCandidateReason, int] = {}
    for candidate in candidates:
        reason_counts[candidate.reason] = reason_counts.get(candidate.reason, 0) + 1
    return ScorePerformanceRecalculationCandidateResult(
        candidates=candidates,
        reason_counts=reason_counts,
    )


def _candidate(
    score_id: int,
    reason: RecalculationCandidateReason,
) -> ScorePerformanceRecalculationCandidate:
    return ScorePerformanceRecalculationCandidate(
        score_id=score_id,
        reason=reason,
        current_calculation_id=None,
    )


def _use_case(
    query_repository: _QueryRepository,
    factory: _UnitOfWorkFactory,
    wake: _WakeRecorder | None = None,
) -> CreatePerformanceRecalculationBatchUseCase:
    return CreatePerformanceRecalculationBatchUseCase(
        query_repository=query_repository,
        unit_of_work_factory=cast("UnitOfWorkFactory", cast("object", factory)),
        calculator_identity=_CalculatorIdentity(),
        worker_wake=wake,
    )


def _command(
    *,
    mode: CreatePerformanceRecalculationBatchMode,
    score_id: int | None = 10,
    beatmap_id: int | None = None,
    user_id: int | None = None,
    ruleset: Ruleset | None = None,
    limit: int | None = None,
    full_scope: bool = False,
    include_unavailable: bool = False,
) -> CreatePerformanceRecalculationBatchCommand:
    return CreatePerformanceRecalculationBatchCommand(
        mode=mode,
        score_id=score_id,
        beatmap_id=beatmap_id,
        user_id=user_id,
        ruleset=ruleset,
        limit=limit,
        full_scope=full_scope,
        include_unavailable=include_unavailable,
        requested_at=_NOW,
    )


@pytest.mark.asyncio
async def test_dry_run_returns_candidate_count_and_reason_breakdown_without_uow_or_wake() -> None:
    query = _QueryRepository(
        _candidate_result(
            _candidate(1, RecalculationCandidateReason.UNCALCULATED),
            _candidate(2, RecalculationCandidateReason.STALE),
        )
    )
    factory = _UnitOfWorkFactory()
    wake = _WakeRecorder(factory)
    use_case = _use_case(query, factory, wake)

    result = await use_case.execute(_command(mode=CreatePerformanceRecalculationBatchMode.DRY_RUN))

    assert result.outcome is CreatePerformanceRecalculationBatchOutcome.DRY_RUN
    assert result.candidate_count == 2
    assert result.reason_counts == {
        RecalculationCandidateReason.UNCALCULATED: 1,
        RecalculationCandidateReason.STALE: 1,
    }
    assert result.batch is None
    assert factory.open_count == 0
    assert factory.created_batches == []
    assert factory.commit_count == 0
    assert wake.calls == []


@pytest.mark.asyncio
async def test_execute_saves_filters_provenance_reason_counts_work_items_and_commits() -> None:
    query = _QueryRepository(
        _candidate_result(
            _candidate(101, RecalculationCandidateReason.UNCALCULATED),
            _candidate(102, RecalculationCandidateReason.CALCULATOR_VERSION_MISMATCH),
        )
    )
    factory = _UnitOfWorkFactory()
    wake = _WakeRecorder(factory)
    use_case = _use_case(query, factory, wake)

    result = await use_case.execute(
        _command(
            mode=CreatePerformanceRecalculationBatchMode.EXECUTE,
            score_id=None,
            user_id=55,
            ruleset=Ruleset.OSU,
            limit=25,
            include_unavailable=True,
        )
    )

    assert result.outcome is CreatePerformanceRecalculationBatchOutcome.CREATED
    assert result.batch is not None
    assert result.batch.id == 1
    assert result.candidate_count == 2
    assert result.reason_counts == {
        RecalculationCandidateReason.UNCALCULATED: 1,
        RecalculationCandidateReason.CALCULATOR_VERSION_MISMATCH: 1,
    }
    assert result.filters == {
        "score_id": None,
        "beatmap_id": None,
        "user_id": 55,
        "ruleset": "osu",
        "limit": 25,
        "full_scope": False,
        "include_unavailable": True,
    }
    assert factory.commit_count == 1
    assert len(factory.created_batches) == 1
    batch_command = factory.created_batches[0]
    assert batch_command.filters == result.filters
    assert batch_command.reason_counts == result.reason_counts
    assert batch_command.target_calculator_version == _CALCULATOR_VERSION
    assert batch_command.target_formula_profile is FormulaProfile.VANILLA_RANKED
    assert [work.score_id for work in batch_command.work_items] == [101, 102]
    assert [work.reason for work in batch_command.work_items] == [
        RecalculationCandidateReason.UNCALCULATED,
        RecalculationCandidateReason.CALCULATOR_VERSION_MISMATCH,
    ]
    assert batch_command.created_at == _NOW
    assert wake.calls == [_WakeCall(batch_id=1, commit_count_at_call=1)]


@pytest.mark.asyncio
async def test_execute_without_narrow_filter_and_without_full_scope_is_rejected() -> None:
    query = _QueryRepository(
        _candidate_result(_candidate(1, RecalculationCandidateReason.UNCALCULATED))
    )
    factory = _UnitOfWorkFactory()
    wake = _WakeRecorder(factory)
    use_case = _use_case(query, factory, wake)

    result = await use_case.execute(
        _command(
            mode=CreatePerformanceRecalculationBatchMode.EXECUTE,
            score_id=None,
            limit=100,
            full_scope=False,
        )
    )

    assert result.outcome is CreatePerformanceRecalculationBatchOutcome.REJECTED
    assert result.rejection_reason == "full_scope_required"
    assert query.selections == []
    assert factory.open_count == 0
    assert factory.created_batches == []
    assert factory.commit_count == 0
    assert wake.calls == []


@pytest.mark.asyncio
async def test_include_unavailable_is_preserved_in_filters_and_candidate_selection() -> None:
    query = _QueryRepository(
        _candidate_result(_candidate(7, RecalculationCandidateReason.UNAVAILABLE))
    )
    factory = _UnitOfWorkFactory()
    use_case = _use_case(query, factory)

    result = await use_case.execute(
        _command(
            mode=CreatePerformanceRecalculationBatchMode.DRY_RUN,
            include_unavailable=True,
        )
    )

    assert result.filters["include_unavailable"] is True
    assert len(query.selections) == 1
    assert query.selections[0].include_unavailable is True


@pytest.mark.asyncio
async def test_limit_is_candidate_cap_but_not_full_scope_safety_substitute() -> None:
    query = _QueryRepository(
        _candidate_result(_candidate(1, RecalculationCandidateReason.UNCALCULATED))
    )
    factory = _UnitOfWorkFactory()
    use_case = _use_case(query, factory)

    rejected = await use_case.execute(
        _command(
            mode=CreatePerformanceRecalculationBatchMode.EXECUTE,
            score_id=None,
            limit=1,
            full_scope=False,
        )
    )
    accepted = await use_case.execute(
        _command(
            mode=CreatePerformanceRecalculationBatchMode.DRY_RUN,
            score_id=None,
            limit=1,
            full_scope=True,
        )
    )

    assert rejected.outcome is CreatePerformanceRecalculationBatchOutcome.REJECTED
    assert accepted.outcome is CreatePerformanceRecalculationBatchOutcome.DRY_RUN
    assert len(query.selections) == 1
    assert query.selections[0].limit == 1


@pytest.mark.asyncio
async def test_execute_wakes_batch_worker_after_commit_but_dry_run_does_not_wake() -> None:
    query = _QueryRepository(
        _candidate_result(_candidate(3, RecalculationCandidateReason.FORMULA_PROFILE_MISMATCH))
    )
    factory = _UnitOfWorkFactory()
    wake = _WakeRecorder(factory)
    use_case = _use_case(query, factory, wake)

    dry_run = await use_case.execute(
        _command(mode=CreatePerformanceRecalculationBatchMode.DRY_RUN)
    )
    executed = await use_case.execute(
        _command(mode=CreatePerformanceRecalculationBatchMode.EXECUTE)
    )

    assert dry_run.worker_wake_requested is False
    assert executed.worker_wake_requested is True
    assert wake.calls == [_WakeCall(batch_id=1, commit_count_at_call=1)]
