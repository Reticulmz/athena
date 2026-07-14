"""Tests for requesting score performance calculation work."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, cast, final, override

import pytest

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculation,
    PerformanceCalculationState,
)
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.score_performance import (
    CompleteScorePerformanceCalculation,
    CreateScorePerformanceCalculation,
    MarkScorePerformanceCalculationUnavailable,
    ScorePerformanceCalculationRequestResult,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores.performance import (
    RequestPerformanceCalculationCommand,
    RequestPerformanceCalculationOutcome,
    RequestPerformanceCalculationUseCase,
)

if TYPE_CHECKING:
    from types import TracebackType

    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
    from osu_server.repositories.memory.commands import InMemoryCommandRepositoryState

_NOW = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)
_CALCULATOR_NAME = "rosu-pp-py"
_CALCULATOR_VERSION = "4.0.2"


@dataclass(frozen=True, slots=True)
class _WakeCall:
    score_id: int
    calculation_id: int
    commit_count_at_call: int


class _CommitCounter(Protocol):
    commit_count: int


@final
class _WakeRecorder:
    def __init__(self, factory: _CommitCounter) -> None:
        self._factory: _CommitCounter = factory
        self.calls: list[_WakeCall] = []

    async def wake_score_calculation(self, *, score_id: int, calculation_id: int) -> None:
        self.calls.append(
            _WakeCall(
                score_id=score_id,
                calculation_id=calculation_id,
                commit_count_at_call=self._factory.commit_count,
            )
        )


@final
class _FailingWake:
    async def wake_score_calculation(self, *, score_id: int, calculation_id: int) -> None:
        _ = score_id
        _ = calculation_id
        raise RuntimeError("worker wake failed")


@final
class _CountingUnitOfWorkFactory(InMemoryUnitOfWorkFactory):
    commit_count: int

    def __init__(self) -> None:
        super().__init__()
        self.commit_count = 0

    @override
    def commit_state(self, state: InMemoryCommandRepositoryState) -> None:
        super().commit_state(state)
        self.commit_count += 1

    def reset_commit_count(self) -> None:
        self.commit_count = 0


@final
class _CommitRequiredUnitOfWorkFactory:
    def __init__(
        self,
        *,
        score: Score,
        request_result: ScorePerformanceCalculationRequestResult,
    ) -> None:
        self.commit_count: int = 0
        self.rollback_count: int = 0
        self.score: Score = score
        self.request_result: ScorePerformanceCalculationRequestResult = request_result

    def __call__(self) -> _CommitRequiredUnitOfWork:
        return _CommitRequiredUnitOfWork(self)


@final
class _CommitRequiredUnitOfWork:
    def __init__(self, factory: _CommitRequiredUnitOfWorkFactory) -> None:
        self._factory: _CommitRequiredUnitOfWorkFactory = factory
        self._committed: bool = False
        self.scores = _ScoreLookup(factory.score)
        self.score_performance = _CommitRequiredScorePerformanceRepository(factory.request_result)

    async def __aenter__(self) -> _CommitRequiredUnitOfWork:
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
class _ScoreLookup:
    def __init__(self, score: Score) -> None:
        self._score: Score = score

    async def get_by_id(self, score_id: int) -> Score | None:
        if self._score.id == score_id:
            return self._score
        return None


@final
class _CommitRequiredScorePerformanceRepository:
    def __init__(self, result: ScorePerformanceCalculationRequestResult) -> None:
        self._result: ScorePerformanceCalculationRequestResult = result

    async def create_or_reuse_calculation(
        self,
        command: CreateScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationRequestResult:
        _ = command
        return self._result


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED])
async def test_eligible_passed_score_creates_calculation_row_and_wakes_after_commit(
    status: BeatmapRankStatus,
) -> None:
    factory = _CountingUnitOfWorkFactory()
    score_id = await _persist_score(factory, _score(status=status))
    factory.reset_commit_count()
    wake = _WakeRecorder(factory)
    use_case = RequestPerformanceCalculationUseCase(
        unit_of_work_factory=factory,
        worker_wake=wake,
    )

    result = await use_case.execute(_command(score_id=score_id))

    assert result.outcome is RequestPerformanceCalculationOutcome.CREATED
    assert result.calculation is not None
    assert result.calculation.score_id == score_id
    assert result.calculation.state is PerformanceCalculationState.QUEUED
    assert result.calculation.calculator_name == _CALCULATOR_NAME
    assert result.calculation.calculator_version == _CALCULATOR_VERSION
    assert result.calculation.formula_profile is FormulaProfile.VANILLA_RANKED
    assert result.created is True
    assert result.is_replacement is False
    assert result.worker_wake_requested is True
    assert result.worker_wake_failed is False
    assert factory.commit_count == 1
    assert wake.calls == [
        _WakeCall(
            score_id=score_id,
            calculation_id=_require_calculation_id(result.calculation),
            commit_count_at_call=1,
        )
    ]


@pytest.mark.asyncio
async def test_duplicate_eligible_request_reuses_pending_row_and_wakes_without_duplicate() -> None:
    factory = _CountingUnitOfWorkFactory()
    score_id = await _persist_score(factory, _score())
    factory.reset_commit_count()
    wake = _WakeRecorder(factory)
    use_case = RequestPerformanceCalculationUseCase(
        unit_of_work_factory=factory,
        worker_wake=wake,
    )

    first = await use_case.execute(_command(score_id=score_id))
    second = await use_case.execute(_command(score_id=score_id))

    assert first.outcome is RequestPerformanceCalculationOutcome.CREATED
    assert second.outcome is RequestPerformanceCalculationOutcome.REUSED_PENDING
    assert second.calculation is not None
    assert first.calculation is not None
    assert second.calculation.id == first.calculation.id
    assert second.created is False
    assert second.worker_wake_requested is True
    assert factory.commit_count == 1
    assert _performance_row_count(factory) == 1
    assert wake.calls == [
        _WakeCall(
            score_id=score_id,
            calculation_id=_require_calculation_id(first.calculation),
            commit_count_at_call=1,
        ),
        _WakeCall(
            score_id=score_id,
            calculation_id=_require_calculation_id(second.calculation),
            commit_count_at_call=1,
        ),
    ]


@pytest.mark.asyncio
async def test_worker_wake_failure_does_not_rollback_durable_calculation_row() -> None:
    factory = _CountingUnitOfWorkFactory()
    score_id = await _persist_score(factory, _score())
    factory.reset_commit_count()
    use_case = RequestPerformanceCalculationUseCase(
        unit_of_work_factory=factory,
        worker_wake=_FailingWake(),
    )

    result = await use_case.execute(_command(score_id=score_id))

    assert result.outcome is RequestPerformanceCalculationOutcome.CREATED
    assert result.calculation is not None
    assert result.worker_wake_requested is True
    assert result.worker_wake_failed is True
    assert result.worker_wake_error == "worker wake failed"
    assert factory.commit_count == 1
    assert _performance_row_count(factory) == 1
    async with factory() as uow:
        current = await uow.score_performance.get_current_for_score(score_id)
    assert current is not None
    assert current.id == result.calculation.id
    assert current.state is PerformanceCalculationState.QUEUED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal_state",
    [PerformanceCalculationState.COMPLETED, PerformanceCalculationState.UNAVAILABLE],
)
async def test_matching_terminal_row_is_noop_without_worker_wake(
    terminal_state: PerformanceCalculationState,
) -> None:
    factory = _CountingUnitOfWorkFactory()
    score_id = await _persist_score(factory, _score())
    calculation_id = await _create_pending_calculation(factory, score_id=score_id)
    await _finalize_calculation(factory, calculation_id=calculation_id, state=terminal_state)
    factory.reset_commit_count()
    wake = _WakeRecorder(factory)
    use_case = RequestPerformanceCalculationUseCase(
        unit_of_work_factory=factory,
        worker_wake=wake,
    )

    result = await use_case.execute(_command(score_id=score_id))

    assert result.outcome is RequestPerformanceCalculationOutcome.ALREADY_CURRENT
    assert result.calculation is not None
    assert result.calculation.id == calculation_id
    assert result.calculation.state is terminal_state
    assert result.created is False
    assert result.worker_wake_requested is False
    assert factory.commit_count == 0
    assert _performance_row_count(factory) == 1
    assert wake.calls == []


@pytest.mark.asyncio
async def test_stale_completed_provenance_creates_replacement_without_overwriting_current() -> (
    None
):
    factory = _CountingUnitOfWorkFactory()
    score_id = await _persist_score(factory, _score())
    current_id = await _create_pending_calculation(
        factory,
        score_id=score_id,
        calculator_version="3.9.0",
    )
    await _finalize_calculation(
        factory,
        calculation_id=current_id,
        state=PerformanceCalculationState.COMPLETED,
        calculator_version="3.9.0",
    )
    factory.reset_commit_count()
    wake = _WakeRecorder(factory)
    use_case = RequestPerformanceCalculationUseCase(
        unit_of_work_factory=factory,
        worker_wake=wake,
    )

    result = await use_case.execute(_command(score_id=score_id))

    assert result.outcome is RequestPerformanceCalculationOutcome.CREATED_REPLACEMENT
    assert result.calculation is not None
    assert result.calculation.id != current_id
    assert result.calculation.is_current is False
    assert result.calculation.state is PerformanceCalculationState.QUEUED
    assert result.created is True
    assert result.is_replacement is True
    assert result.worker_wake_requested is True
    assert factory.commit_count == 1
    assert _performance_row_count(factory) == 2
    async with factory() as uow:
        current = await uow.score_performance.get_current_for_score(score_id)
    assert current is not None
    assert current.id == current_id
    assert current.state is PerformanceCalculationState.COMPLETED
    assert wake.calls == [
        _WakeCall(
            score_id=score_id,
            calculation_id=_require_calculation_id(result.calculation),
            commit_count_at_call=1,
        )
    ]


@pytest.mark.asyncio
async def test_reused_replacement_internal_mutation_commits_before_wake() -> None:
    score_id = 77
    calculation = _calculation(
        calculation_id=12,
        score_id=score_id,
        is_current=False,
    )
    factory = _CommitRequiredUnitOfWorkFactory(
        score=replace(_score(), id=score_id),
        request_result=ScorePerformanceCalculationRequestResult(
            calculation=calculation,
            created=False,
            is_replacement=True,
            requires_commit=True,
        ),
    )
    wake = _WakeRecorder(factory)
    use_case = RequestPerformanceCalculationUseCase(
        unit_of_work_factory=cast("UnitOfWorkFactory", cast("object", factory)),
        worker_wake=wake,
    )

    result = await use_case.execute(_command(score_id=score_id))

    assert result.outcome is RequestPerformanceCalculationOutcome.REUSED_REPLACEMENT_PENDING
    assert result.calculation is not None
    assert result.calculation.id == calculation.id
    assert result.created is False
    assert result.is_replacement is True
    assert result.worker_wake_requested is True
    assert factory.commit_count == 1
    assert factory.rollback_count == 0
    assert wake.calls == [
        _WakeCall(
            score_id=score_id,
            calculation_id=_require_calculation_id(calculation),
            commit_count_at_call=1,
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "passed", "eligibility_reason"),
    [
        (BeatmapRankStatus.LOVED, True, "beatmap_status_out_of_scope"),
        (BeatmapRankStatus.QUALIFIED, True, "beatmap_status_out_of_scope"),
        (BeatmapRankStatus.RANKED, False, "score_failed"),
    ],
)
async def test_out_of_scope_saved_score_is_skipped_without_performance_row(
    status: BeatmapRankStatus,
    passed: bool,
    eligibility_reason: str,
) -> None:
    factory = _CountingUnitOfWorkFactory()
    score = _score(status=status, passed=passed)
    score_id = await _persist_score(factory, score)
    factory.reset_commit_count()
    wake = _WakeRecorder(factory)
    use_case = RequestPerformanceCalculationUseCase(
        unit_of_work_factory=factory,
        worker_wake=wake,
    )

    result = await use_case.execute(_command(score_id=score_id))

    assert result.outcome is RequestPerformanceCalculationOutcome.SKIPPED_OUT_OF_SCOPE
    assert result.eligibility_reason == eligibility_reason
    assert result.calculation is None
    assert result.worker_wake_requested is False
    assert factory.commit_count == 0
    assert _performance_row_count(factory) == 0
    async with factory() as uow:
        accepted_score = await uow.scores.get_by_id(score_id)
    assert accepted_score == replace(score, id=score_id)
    assert wake.calls == []


@pytest.mark.asyncio
async def test_missing_score_returns_missing_result_without_performance_row() -> None:
    factory = _CountingUnitOfWorkFactory()
    wake = _WakeRecorder(factory)
    use_case = RequestPerformanceCalculationUseCase(
        unit_of_work_factory=factory,
        worker_wake=wake,
    )

    result = await use_case.execute(_command(score_id=404))

    assert result.outcome is RequestPerformanceCalculationOutcome.SCORE_NOT_FOUND
    assert result.calculation is None
    assert result.worker_wake_requested is False
    assert factory.commit_count == 0
    assert _performance_row_count(factory) == 0
    assert wake.calls == []


def _score(
    *,
    status: BeatmapRankStatus | str | None = BeatmapRankStatus.RANKED,
    passed: bool = True,
    online_checksum: str = "abcdef0123456789abcdef0123456789",
) -> Score:
    status_value = status.value if isinstance(status, BeatmapRankStatus) else status
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
        passed=passed,
        perfect=False,
        client_version="b20250101",
        submitted_at=_NOW,
        beatmap_status_at_submission=BeatmapRankStatus(status_value)
        if status_value is not None
        else None,
    )


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
        calculator_name=_CALCULATOR_NAME,
        calculator_version=_CALCULATOR_VERSION,
        formula_profile=FormulaProfile.VANILLA_RANKED,
        beatmap_file_attachment_id=None,
        beatmap_file_checksum_md5=None,
        unavailable_reason=None,
        calculated_at=None,
    )


def _command(*, score_id: int) -> RequestPerformanceCalculationCommand:
    return RequestPerformanceCalculationCommand(
        score_id=score_id,
        calculator_name=_CALCULATOR_NAME,
        calculator_version=_CALCULATOR_VERSION,
        requested_at=_NOW,
    )


async def _persist_score(factory: _CountingUnitOfWorkFactory, score: Score) -> int:
    async with factory() as uow:
        created = await uow.scores.create(score)
        await uow.commit()
    assert created.id is not None
    return created.id


async def _create_pending_calculation(
    factory: _CountingUnitOfWorkFactory,
    *,
    score_id: int,
    calculator_version: str = _CALCULATOR_VERSION,
) -> int:
    async with factory() as uow:
        result = await uow.score_performance.create_or_reuse_calculation(
            CreateScorePerformanceCalculation(
                score_id=score_id,
                calculator_name=_CALCULATOR_NAME,
                calculator_version=calculator_version,
                formula_profile=FormulaProfile.VANILLA_RANKED,
                requested_at=_NOW,
            )
        )
        await uow.commit()
    return _require_calculation_id(result.calculation)


async def _finalize_calculation(
    factory: _CountingUnitOfWorkFactory,
    *,
    calculation_id: int,
    state: PerformanceCalculationState,
    calculator_version: str = _CALCULATOR_VERSION,
) -> None:
    async with factory() as uow:
        if state is PerformanceCalculationState.COMPLETED:
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
        elif state is PerformanceCalculationState.UNAVAILABLE:
            _ = await uow.score_performance.mark_unavailable(
                MarkScorePerformanceCalculationUnavailable(
                    calculation_id=calculation_id,
                    calculator_name=_CALCULATOR_NAME,
                    calculator_version=calculator_version,
                    formula_profile=FormulaProfile.VANILLA_RANKED,
                    beatmap_file_attachment_id=55,
                    beatmap_file_checksum_md5="a" * 32,
                    reason="calculator_input_invalid",
                    calculated_at=_NOW,
                )
            )
        else:
            msg = f"unsupported terminal state for test: {state.value}"
            raise ValueError(msg)
        await uow.commit()


def _performance_row_count(factory: _CountingUnitOfWorkFactory) -> int:
    return len(factory.snapshot().performance_calculations_by_id)


def _require_calculation_id(calculation: PerformanceCalculation) -> int:
    if calculation.id is None:
        msg = "calculation id must be assigned"
        raise AssertionError(msg)
    return calculation.id
