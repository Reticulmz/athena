"""Tests for executing score performance calculation work."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, final, override

import pytest

from osu_server.domain.beatmaps import BeatmapFetchState, BeatmapFileState, BeatmapRankStatus
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculation,
    PerformanceCalculationState,
)
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.domain.scores.user_stats import UserStatsScope
from osu_server.infrastructure.performance import (
    PerformanceCalculatorCompleted,
    PerformanceCalculatorInput,
    PerformanceCalculatorUnavailable,
    PerformanceCalculatorUnavailableReason,
)
from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
    PerformanceCompletionSignalPayload,
)
from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
    BeatmapPerformanceBestScope,
    UpsertBeatmapPerformanceBest,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    CompleteScorePerformanceCalculation,
    CreateScorePerformanceCalculation,
    UpdateScorePerformanceCalculationState,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores.performance import (
    ExecutePerformanceCalculationCommand,
    ExecutePerformanceCalculationOutcome,
    ExecutePerformanceCalculationUseCase,
    PerformanceBeatmapFilePending,
    PerformanceBeatmapFilePendingReason,
    PerformanceBeatmapFileProvenance,
    PerformanceBeatmapFileQuery,
    PerformanceBeatmapFileReady,
    PerformanceBeatmapFileResult,
    PerformanceBeatmapFileUnavailable,
    PerformanceBeatmapFileUnavailableReason,
    PerformanceRuntimeSettings,
)

if TYPE_CHECKING:
    from osu_server.repositories.memory.commands import InMemoryCommandRepositoryState

_NOW = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)
_CALCULATOR_NAME = "rosu-pp-py"
_CALCULATOR_VERSION = "4.0.2"
_CLAIM_OWNER = "worker-1"


@dataclass(frozen=True, slots=True)
class _SignalCall:
    payload: PerformanceCompletionSignalPayload
    commit_count_at_call: int


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
class _FileProvider:
    def __init__(
        self,
        result: PerformanceBeatmapFileResult,
        *,
        factory: _CountingUnitOfWorkFactory | None = None,
        calculation_id: int | None = None,
        expected_state_at_call: PerformanceCalculationState | None = None,
    ) -> None:
        self._result = result
        self._factory = factory
        self._calculation_id = calculation_id
        self._expected_state_at_call = expected_state_at_call
        self.queries: list[PerformanceBeatmapFileQuery] = []

    async def provide(
        self,
        query: PerformanceBeatmapFileQuery,
    ) -> PerformanceBeatmapFileResult:
        if self._expected_state_at_call is not None:
            assert self._factory is not None
            assert self._calculation_id is not None
            calculation = self._factory.snapshot().performance_calculations_by_id.get(
                self._calculation_id
            )
            assert calculation is not None
            assert calculation.state is self._expected_state_at_call
        self.queries.append(query)
        return self._result


@final
class _Calculator:
    def __init__(
        self,
        result: PerformanceCalculatorCompleted | PerformanceCalculatorUnavailable,
        *,
        factory: _CountingUnitOfWorkFactory | None = None,
        calculation_id: int | None = None,
        calculator_version: str = _CALCULATOR_VERSION,
        expected_state_at_call: PerformanceCalculationState | None = None,
    ) -> None:
        self._result = result
        self._factory = factory
        self._calculation_id = calculation_id
        self._calculator_version = calculator_version
        self._expected_state_at_call = expected_state_at_call
        self.inputs: list[PerformanceCalculatorInput] = []

    def calculator_name(self) -> str:
        return _CALCULATOR_NAME

    def calculator_version(self) -> str:
        return self._calculator_version

    def calculate(
        self,
        input_data: PerformanceCalculatorInput,
    ) -> PerformanceCalculatorCompleted | PerformanceCalculatorUnavailable:
        if self._expected_state_at_call is not None:
            assert self._factory is not None
            assert self._calculation_id is not None
            calculation = self._factory.snapshot().performance_calculations_by_id.get(
                self._calculation_id
            )
            assert calculation is not None
            assert calculation.state is self._expected_state_at_call
        self.inputs.append(input_data)
        return self._result


@final
class _CompletionSignal:
    def __init__(self, factory: _CountingUnitOfWorkFactory) -> None:
        self._factory = factory
        self.calls: list[_SignalCall] = []

    async def notify(self, payload: PerformanceCompletionSignalPayload) -> None:
        self.calls.append(
            _SignalCall(
                payload=payload,
                commit_count_at_call=self._factory.commit_count,
            )
        )

    async def wait(self, score_id: int, timeout: timedelta) -> bool:
        _ = score_id
        _ = timeout
        return False


@pytest.mark.asyncio
async def test_execute_calculation_claims_calculates_commits_and_signals_completion() -> None:
    factory = _CountingUnitOfWorkFactory()
    score = _score()
    score_id = await _persist_score(factory, score)
    calculation_id = await _create_pending_calculation(factory, score_id=score_id)
    factory.reset_commit_count()
    file_provider = _FileProvider(
        _ready_file(),
        factory=factory,
        calculation_id=calculation_id,
        expected_state_at_call=PerformanceCalculationState.FETCHING_FILE,
    )
    calculator = _Calculator(
        PerformanceCalculatorCompleted(
            pp=Decimal("123.456789"),
            star_rating=Decimal("5.43210"),
        ),
        factory=factory,
        calculation_id=calculation_id,
        expected_state_at_call=PerformanceCalculationState.CALCULATING,
    )
    completion_signal = _CompletionSignal(factory)
    use_case = _use_case(
        factory,
        file_provider=file_provider,
        calculator=calculator,
        completion_signal=completion_signal,
    )

    result = await use_case.execute(_command(calculation_id=calculation_id))

    assert result.outcome is ExecutePerformanceCalculationOutcome.COMPLETED
    assert result.calculation is not None
    assert result.calculation.id == calculation_id
    assert result.calculation.state is PerformanceCalculationState.COMPLETED
    assert result.calculation.pp == Decimal("123.456789")
    assert result.calculation.star_rating == Decimal("5.43210")
    assert result.calculation.calculator_name == _CALCULATOR_NAME
    assert result.calculation.calculator_version == _CALCULATOR_VERSION
    assert result.calculation.formula_profile is FormulaProfile.VANILLA_RANKED
    assert result.calculation.beatmap_file_attachment_id == 55
    assert result.calculation.beatmap_file_checksum_md5 == "a" * 32
    assert result.signal_notified is True
    assert factory.commit_count == 3
    assert file_provider.queries == [PerformanceBeatmapFileQuery(score.beatmap_id)]
    assert len(calculator.inputs) == 1
    assert calculator.inputs[0].score == replace(score, id=score_id)
    assert calculator.inputs[0].osu_file_bytes == b"osu file bytes"
    projection_rows = tuple(factory.snapshot().beatmap_performance_bests_by_id.values())
    assert len(projection_rows) == 1
    projection = projection_rows[0]
    assert projection.scope == BeatmapPerformanceBestScope(
        user_id=score.user_id,
        beatmap_id=score.beatmap_id,
        ruleset=score.ruleset,
        playstyle=score.playstyle,
    )
    assert projection.score_id == score_id
    assert projection.performance_calculation_id == calculation_id
    assert projection.pp == Decimal("123.456789")
    assert projection.accuracy == score.accuracy
    assert projection.score == score.score
    async with factory() as uow:
        stats_projection = await uow.current_user_stats.get(
            UserStatsScope(
                user_id=score.user_id,
                ruleset=score.ruleset,
                playstyle=score.playstyle,
            )
        )
    assert stats_projection is not None
    assert stats_projection.pp == Decimal("123.456789")
    assert stats_projection.accuracy == score.accuracy
    assert stats_projection.play_count == 1
    assert stats_projection.ranked_score == score.score
    assert stats_projection.total_score == score.score
    assert stats_projection.max_combo == score.max_combo
    assert stats_projection.hit_totals.count_300 == 300
    assert stats_projection.hit_totals.count_100 == 50
    assert stats_projection.hit_totals.count_50 == 10
    assert stats_projection.hit_totals.count_miss == 5
    assert completion_signal.calls == [
        _SignalCall(
            payload=PerformanceCompletionSignalPayload(
                score_id=score_id,
                calculation_id=calculation_id,
                state=PerformanceCalculationState.COMPLETED,
            ),
            commit_count_at_call=3,
        )
    ]


@pytest.mark.asyncio
async def test_execute_calculation_rebuilds_projection_when_replacement_pp_drops() -> None:
    factory = _CountingUnitOfWorkFactory()
    old_score = _score(
        score=900_000,
        accuracy=0.99,
        online_checksum="1" * 32,
        submitted_at=_NOW,
    )
    fallback_score = _score(
        score=850_000,
        accuracy=0.97,
        online_checksum="2" * 32,
        submitted_at=_NOW + timedelta(seconds=1),
    )
    old_score_id = await _persist_score(factory, old_score)
    fallback_score_id = await _persist_score(factory, fallback_score)
    old_current_id = await _complete_current_calculation(
        factory,
        score_id=old_score_id,
        pp=Decimal("250"),
        calculator_version="4.0.2",
    )
    fallback_calculation_id = await _complete_current_calculation(
        factory,
        score_id=fallback_score_id,
        pp=Decimal("180"),
        calculator_version="4.0.2",
    )
    await _seed_projection(
        factory,
        score=replace(old_score, id=old_score_id),
        calculation_id=old_current_id,
        pp=Decimal("250"),
    )
    replacement_id = await _create_replacement_calculation(
        factory,
        score_id=old_score_id,
        calculator_version="4.1.0",
    )
    factory.reset_commit_count()
    use_case = _use_case(
        factory,
        file_provider=_FileProvider(_ready_file()),
        calculator=_Calculator(
            PerformanceCalculatorCompleted(
                pp=Decimal("150"),
                star_rating=Decimal("4.5"),
            ),
            calculator_version="4.1.0",
        ),
        completion_signal=_CompletionSignal(factory),
    )

    result = await use_case.execute(_command(calculation_id=replacement_id))

    assert result.outcome is ExecutePerformanceCalculationOutcome.COMPLETED
    async with factory() as uow:
        projection = await uow.beatmap_performance_bests.get_best(
            BeatmapPerformanceBestScope(
                user_id=old_score.user_id,
                beatmap_id=old_score.beatmap_id,
                ruleset=old_score.ruleset,
                playstyle=old_score.playstyle,
            )
        )
        old_current = await uow.score_performance.get_current_for_score(old_score_id)
        stats_projection = await uow.current_user_stats.get(
            UserStatsScope(
                user_id=old_score.user_id,
                ruleset=old_score.ruleset,
                playstyle=old_score.playstyle,
            )
        )

    assert old_current is not None
    assert old_current.id == replacement_id
    assert old_current.pp == Decimal("150")
    assert projection is not None
    assert projection.score_id == fallback_score_id
    assert projection.performance_calculation_id == fallback_calculation_id
    assert projection.pp == Decimal("180")
    assert stats_projection is not None
    assert stats_projection.pp == Decimal("180")


@pytest.mark.asyncio
async def test_execute_calculation_rebuilds_projection_when_replacement_unavailable() -> None:
    factory = _CountingUnitOfWorkFactory()
    old_score = _score(
        score=900_000,
        accuracy=0.99,
        online_checksum="1" * 32,
        submitted_at=_NOW,
    )
    fallback_score = _score(
        score=850_000,
        accuracy=0.97,
        online_checksum="2" * 32,
        submitted_at=_NOW + timedelta(seconds=1),
    )
    old_score_id = await _persist_score(factory, old_score)
    fallback_score_id = await _persist_score(factory, fallback_score)
    old_current_id = await _complete_current_calculation(
        factory,
        score_id=old_score_id,
        pp=Decimal("250"),
        calculator_version="4.0.2",
    )
    fallback_calculation_id = await _complete_current_calculation(
        factory,
        score_id=fallback_score_id,
        pp=Decimal("180"),
        calculator_version="4.0.2",
    )
    await _seed_projection(
        factory,
        score=replace(old_score, id=old_score_id),
        calculation_id=old_current_id,
        pp=Decimal("250"),
    )
    replacement_id = await _create_replacement_calculation(
        factory,
        score_id=old_score_id,
        calculator_version="4.1.0",
    )
    factory.reset_commit_count()
    use_case = _use_case(
        factory,
        file_provider=_FileProvider(_ready_file()),
        calculator=_Calculator(
            PerformanceCalculatorUnavailable(
                PerformanceCalculatorUnavailableReason.CALCULATOR_INPUT_INVALID
            ),
            calculator_version="4.1.0",
        ),
        completion_signal=_CompletionSignal(factory),
    )

    result = await use_case.execute(_command(calculation_id=replacement_id))

    assert result.outcome is ExecutePerformanceCalculationOutcome.UNAVAILABLE
    async with factory() as uow:
        projection = await uow.beatmap_performance_bests.get_best(
            BeatmapPerformanceBestScope(
                user_id=old_score.user_id,
                beatmap_id=old_score.beatmap_id,
                ruleset=old_score.ruleset,
                playstyle=old_score.playstyle,
            )
        )
        old_current = await uow.score_performance.get_current_for_score(old_score_id)
        stats_projection = await uow.current_user_stats.get(
            UserStatsScope(
                user_id=old_score.user_id,
                ruleset=old_score.ruleset,
                playstyle=old_score.playstyle,
            )
        )

    assert old_current is not None
    assert old_current.id == replacement_id
    assert old_current.state is PerformanceCalculationState.UNAVAILABLE
    assert projection is not None
    assert projection.score_id == fallback_score_id
    assert projection.performance_calculation_id == fallback_calculation_id
    assert projection.pp == Decimal("180")
    assert stats_projection is not None
    assert stats_projection.pp == Decimal("180")


@pytest.mark.asyncio
async def test_execute_calculation_keeps_temporary_file_input_pending_without_signal() -> None:
    factory = _CountingUnitOfWorkFactory()
    score_id = await _persist_score(factory, _score())
    calculation_id = await _create_pending_calculation(factory, score_id=score_id)
    factory.reset_commit_count()
    file_provider = _FileProvider(_pending_file())
    calculator = _Calculator(
        PerformanceCalculatorCompleted(
            pp=Decimal("999"),
            star_rating=Decimal("9"),
        )
    )
    completion_signal = _CompletionSignal(factory)
    use_case = _use_case(
        factory,
        file_provider=file_provider,
        calculator=calculator,
        completion_signal=completion_signal,
    )

    result = await use_case.execute(_command(calculation_id=calculation_id))

    assert result.outcome is ExecutePerformanceCalculationOutcome.PENDING_INPUT
    assert result.calculation is not None
    assert result.calculation.id == calculation_id
    assert result.calculation.state is PerformanceCalculationState.FETCHING_FILE
    assert result.pending_reason == PerformanceBeatmapFilePendingReason.OSU_FILE_FETCH_PENDING
    assert result.signal_notified is False
    assert factory.commit_count == 1
    assert calculator.inputs == []
    assert completion_signal.calls == []
    async with factory() as uow:
        current = await uow.score_performance.get_current_for_score(score_id)
    assert current is not None
    assert current.state is PerformanceCalculationState.FETCHING_FILE
    assert current.unavailable_reason is None


@pytest.mark.asyncio
async def test_execute_calculation_retries_from_fetching_file_state() -> None:
    factory = _CountingUnitOfWorkFactory()
    score = _score()
    score_id = await _persist_score(factory, score)
    calculation_id = await _create_pending_calculation(factory, score_id=score_id)
    pending_use_case = _use_case(
        factory,
        file_provider=_FileProvider(_pending_file()),
        calculator=_Calculator(
            PerformanceCalculatorCompleted(
                pp=Decimal("999"),
                star_rating=Decimal("9"),
            )
        ),
        completion_signal=_CompletionSignal(factory),
    )

    pending_result = await pending_use_case.execute(_command(calculation_id=calculation_id))

    assert pending_result.outcome is ExecutePerformanceCalculationOutcome.PENDING_INPUT
    factory.reset_commit_count()
    file_provider = _FileProvider(
        _ready_file(),
        factory=factory,
        calculation_id=calculation_id,
        expected_state_at_call=PerformanceCalculationState.FETCHING_FILE,
    )
    calculator = _Calculator(
        PerformanceCalculatorCompleted(
            pp=Decimal("123.456789"),
            star_rating=Decimal("5.43210"),
        ),
        factory=factory,
        calculation_id=calculation_id,
        expected_state_at_call=PerformanceCalculationState.CALCULATING,
    )
    completion_signal = _CompletionSignal(factory)
    retry_use_case = _use_case(
        factory,
        file_provider=file_provider,
        calculator=calculator,
        completion_signal=completion_signal,
    )

    result = await retry_use_case.execute(
        _command(
            calculation_id=calculation_id,
            claimed_at=_NOW + timedelta(minutes=6),
        )
    )

    assert result.outcome is ExecutePerformanceCalculationOutcome.COMPLETED
    assert result.calculation is not None
    assert result.calculation.state is PerformanceCalculationState.COMPLETED
    assert result.calculation.pp == Decimal("123.456789")
    assert factory.commit_count == 3
    assert file_provider.queries == [PerformanceBeatmapFileQuery(score.beatmap_id)]
    assert len(calculator.inputs) == 1
    assert completion_signal.calls == [
        _SignalCall(
            payload=PerformanceCompletionSignalPayload(
                score_id=score_id,
                calculation_id=calculation_id,
                state=PerformanceCalculationState.COMPLETED,
            ),
            commit_count_at_call=3,
        )
    ]


@pytest.mark.asyncio
async def test_execute_calculation_retries_from_calculating_state() -> None:
    factory = _CountingUnitOfWorkFactory()
    score = _score()
    score_id = await _persist_score(factory, score)
    calculation_id = await _create_pending_calculation(factory, score_id=score_id)
    await _advance_calculation_to_calculating(factory, calculation_id=calculation_id)
    factory.reset_commit_count()
    file_provider = _FileProvider(
        _ready_file(),
        factory=factory,
        calculation_id=calculation_id,
        expected_state_at_call=PerformanceCalculationState.CALCULATING,
    )
    calculator = _Calculator(
        PerformanceCalculatorCompleted(
            pp=Decimal("123.456789"),
            star_rating=Decimal("5.43210"),
        ),
        factory=factory,
        calculation_id=calculation_id,
        expected_state_at_call=PerformanceCalculationState.CALCULATING,
    )
    completion_signal = _CompletionSignal(factory)
    use_case = _use_case(
        factory,
        file_provider=file_provider,
        calculator=calculator,
        completion_signal=completion_signal,
    )

    result = await use_case.execute(_command(calculation_id=calculation_id))

    assert result.outcome is ExecutePerformanceCalculationOutcome.COMPLETED
    assert result.calculation is not None
    assert result.calculation.state is PerformanceCalculationState.COMPLETED
    assert result.calculation.pp == Decimal("123.456789")
    assert factory.commit_count == 2
    assert file_provider.queries == [PerformanceBeatmapFileQuery(score.beatmap_id)]
    assert len(calculator.inputs) == 1
    assert completion_signal.calls == [
        _SignalCall(
            payload=PerformanceCompletionSignalPayload(
                score_id=score_id,
                calculation_id=calculation_id,
                state=PerformanceCalculationState.COMPLETED,
            ),
            commit_count_at_call=2,
        )
    ]


@pytest.mark.asyncio
async def test_execute_calculation_marks_permanent_file_failure_unavailable_and_signals() -> None:
    factory = _CountingUnitOfWorkFactory()
    score_id = await _persist_score(factory, _score())
    calculation_id = await _create_pending_calculation(factory, score_id=score_id)
    factory.reset_commit_count()
    file_provider = _FileProvider(_unavailable_file())
    calculator = _Calculator(
        PerformanceCalculatorCompleted(
            pp=Decimal("999"),
            star_rating=Decimal("9"),
        )
    )
    completion_signal = _CompletionSignal(factory)
    use_case = _use_case(
        factory,
        file_provider=file_provider,
        calculator=calculator,
        completion_signal=completion_signal,
    )

    result = await use_case.execute(_command(calculation_id=calculation_id))

    assert result.outcome is ExecutePerformanceCalculationOutcome.UNAVAILABLE
    assert result.calculation is not None
    assert result.calculation.state is PerformanceCalculationState.UNAVAILABLE
    assert (
        result.calculation.unavailable_reason
        == PerformanceBeatmapFileUnavailableReason.OSU_FILE_FETCH_FAILED.value
    )
    assert result.calculation.beatmap_file_attachment_id is None
    assert result.signal_notified is True
    assert factory.commit_count == 2
    assert calculator.inputs == []
    assert completion_signal.calls == [
        _SignalCall(
            payload=PerformanceCompletionSignalPayload(
                score_id=score_id,
                calculation_id=calculation_id,
                state=PerformanceCalculationState.UNAVAILABLE,
            ),
            commit_count_at_call=2,
        )
    ]


@pytest.mark.asyncio
async def test_execute_calculation_marks_calculator_failure_unavailable_with_file_provenance() -> (
    None
):
    factory = _CountingUnitOfWorkFactory()
    score_id = await _persist_score(factory, _score())
    calculation_id = await _create_pending_calculation(factory, score_id=score_id)
    factory.reset_commit_count()
    calculator = _Calculator(
        PerformanceCalculatorUnavailable(
            PerformanceCalculatorUnavailableReason.CALCULATOR_INPUT_INVALID
        ),
        factory=factory,
        calculation_id=calculation_id,
        expected_state_at_call=PerformanceCalculationState.CALCULATING,
    )
    completion_signal = _CompletionSignal(factory)
    use_case = _use_case(
        factory,
        file_provider=_FileProvider(_ready_file()),
        calculator=calculator,
        completion_signal=completion_signal,
    )

    result = await use_case.execute(_command(calculation_id=calculation_id))

    assert result.outcome is ExecutePerformanceCalculationOutcome.UNAVAILABLE
    assert result.calculation is not None
    assert result.calculation.state is PerformanceCalculationState.UNAVAILABLE
    assert (
        result.calculation.unavailable_reason
        == PerformanceCalculatorUnavailableReason.CALCULATOR_INPUT_INVALID.value
    )
    assert result.calculation.beatmap_file_attachment_id == 55
    assert result.calculation.beatmap_file_checksum_md5 == "a" * 32
    assert result.signal_notified is True
    assert factory.commit_count == 3
    assert completion_signal.calls == [
        _SignalCall(
            payload=PerformanceCompletionSignalPayload(
                score_id=score_id,
                calculation_id=calculation_id,
                state=PerformanceCalculationState.UNAVAILABLE,
            ),
            commit_count_at_call=3,
        )
    ]


@pytest.mark.asyncio
async def test_execute_calculation_does_not_finalize_or_signal_when_claim_conflicts() -> None:
    factory = _CountingUnitOfWorkFactory()
    factory.reset_commit_count()
    file_provider = _FileProvider(_ready_file())
    calculator = _Calculator(
        PerformanceCalculatorCompleted(
            pp=Decimal("123"),
            star_rating=Decimal("5"),
        )
    )
    completion_signal = _CompletionSignal(factory)
    use_case = _use_case(
        factory,
        file_provider=file_provider,
        calculator=calculator,
        completion_signal=completion_signal,
    )

    result = await use_case.execute(_command(calculation_id=404))

    assert result.outcome is ExecutePerformanceCalculationOutcome.CLAIM_NOT_ACQUIRED
    assert result.calculation is None
    assert result.signal_notified is False
    assert factory.commit_count == 0
    assert file_provider.queries == []
    assert calculator.inputs == []
    assert completion_signal.calls == []


@pytest.mark.asyncio
async def test_execute_calculation_marks_missing_score_unavailable_and_reports_it() -> None:
    factory = _CountingUnitOfWorkFactory()
    missing_score_id = 9999
    calculation_id = await _create_pending_calculation(factory, score_id=missing_score_id)
    factory.reset_commit_count()
    file_provider = _FileProvider(_ready_file())
    calculator = _Calculator(
        PerformanceCalculatorCompleted(
            pp=Decimal("123"),
            star_rating=Decimal("5"),
        )
    )
    completion_signal = _CompletionSignal(factory)
    use_case = _use_case(
        factory,
        file_provider=file_provider,
        calculator=calculator,
        completion_signal=completion_signal,
    )

    result = await use_case.execute(_command(calculation_id=calculation_id))

    assert result.outcome is ExecutePerformanceCalculationOutcome.SCORE_NOT_FOUND
    assert result.calculation is not None
    assert result.calculation.state is PerformanceCalculationState.UNAVAILABLE
    assert result.unavailable_reason == "score_not_found"
    assert result.signal_notified is True
    assert factory.commit_count == 1
    assert file_provider.queries == []
    assert calculator.inputs == []
    assert completion_signal.calls == [
        _SignalCall(
            payload=PerformanceCompletionSignalPayload(
                score_id=missing_score_id,
                calculation_id=calculation_id,
                state=PerformanceCalculationState.UNAVAILABLE,
            ),
            commit_count_at_call=1,
        )
    ]


def _use_case(
    factory: _CountingUnitOfWorkFactory,
    *,
    file_provider: _FileProvider,
    calculator: _Calculator,
    completion_signal: _CompletionSignal,
) -> ExecutePerformanceCalculationUseCase:
    return ExecutePerformanceCalculationUseCase(
        unit_of_work_factory=factory,
        beatmap_file_provider=file_provider,
        calculator=calculator,
        completion_signal=completion_signal,
        settings=PerformanceRuntimeSettings(claim_timeout=timedelta(minutes=5)),
    )


def _command(
    *,
    calculation_id: int,
    claimed_at: datetime = _NOW,
) -> ExecutePerformanceCalculationCommand:
    return ExecutePerformanceCalculationCommand(
        calculation_id=calculation_id,
        claim_owner=_CLAIM_OWNER,
        claimed_at=claimed_at,
    )


def _score(
    *,
    score: int = 500_000,
    accuracy: float = 0.95,
    online_checksum: str = "abcdef0123456789abcdef0123456789",
    submitted_at: datetime = _NOW,
) -> Score:
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
        score=score,
        max_combo=350,
        accuracy=accuracy,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="b20250101",
        submitted_at=submitted_at,
        beatmap_status_at_submission=BeatmapRankStatus.RANKED.value,
        leaderboard_eligible_at_submission=True,
    )


def _ready_file() -> PerformanceBeatmapFileReady:
    return PerformanceBeatmapFileReady(
        beatmap_id=2000,
        osu_file_bytes=b"osu file bytes",
        provenance=PerformanceBeatmapFileProvenance(
            beatmap_id=2000,
            beatmap_file_attachment_id=55,
            blob_id=66,
            checksum_md5="a" * 32,
        ),
    )


def _pending_file() -> PerformanceBeatmapFilePending:
    return PerformanceBeatmapFilePending(
        beatmap_id=2000,
        reason=PerformanceBeatmapFilePendingReason.OSU_FILE_FETCH_PENDING,
        metadata_status=BeatmapFetchState.FRESH,
        file_status=BeatmapFileState.PENDING_FETCH,
        mirror_reason=None,
    )


def _unavailable_file() -> PerformanceBeatmapFileUnavailable:
    return PerformanceBeatmapFileUnavailable(
        beatmap_id=2000,
        reason=PerformanceBeatmapFileUnavailableReason.OSU_FILE_FETCH_FAILED,
        metadata_status=BeatmapFetchState.FRESH,
        file_status=BeatmapFileState.FAILED,
        mirror_reason="fetch failed",
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


async def _complete_current_calculation(
    factory: _CountingUnitOfWorkFactory,
    *,
    score_id: int,
    pp: Decimal,
    calculator_version: str,
) -> int:
    calculation_id = await _create_pending_calculation(
        factory,
        score_id=score_id,
        calculator_version=calculator_version,
    )
    async with factory() as uow:
        completed = await uow.score_performance.mark_completed(
            CompleteScorePerformanceCalculation(
                calculation_id=calculation_id,
                pp=pp,
                star_rating=Decimal("5.0"),
                calculator_name=_CALCULATOR_NAME,
                calculator_version=calculator_version,
                formula_profile=FormulaProfile.VANILLA_RANKED,
                beatmap_file_attachment_id=55,
                beatmap_file_checksum_md5="a" * 32,
                calculated_at=_NOW,
            )
        )
        await uow.commit()
    assert completed is not None
    return calculation_id


async def _create_replacement_calculation(
    factory: _CountingUnitOfWorkFactory,
    *,
    score_id: int,
    calculator_version: str,
) -> int:
    return await _create_pending_calculation(
        factory,
        score_id=score_id,
        calculator_version=calculator_version,
    )


async def _seed_projection(
    factory: _CountingUnitOfWorkFactory,
    *,
    score: Score,
    calculation_id: int,
    pp: Decimal,
) -> None:
    async with factory() as uow:
        _ = await uow.beatmap_performance_bests.upsert_if_better(
            UpsertBeatmapPerformanceBest(
                scope=BeatmapPerformanceBestScope(
                    user_id=score.user_id,
                    beatmap_id=score.beatmap_id,
                    ruleset=score.ruleset,
                    playstyle=score.playstyle,
                ),
                score_id=_require_score_id(score),
                performance_calculation_id=calculation_id,
                pp=pp,
                accuracy=score.accuracy,
                score=score.score,
                submitted_at=score.submitted_at,
            )
        )
        await uow.commit()


async def _advance_calculation_to_calculating(
    factory: _CountingUnitOfWorkFactory,
    *,
    calculation_id: int,
) -> None:
    async with factory() as uow:
        fetching = await uow.score_performance.update_pending_calculation_state(
            UpdateScorePerformanceCalculationState(
                calculation_id=calculation_id,
                expected_state=PerformanceCalculationState.QUEUED,
                state=PerformanceCalculationState.FETCHING_FILE,
                transitioned_at=_NOW,
            )
        )
        calculating = await uow.score_performance.update_pending_calculation_state(
            UpdateScorePerformanceCalculationState(
                calculation_id=calculation_id,
                expected_state=PerformanceCalculationState.FETCHING_FILE,
                state=PerformanceCalculationState.CALCULATING,
                transitioned_at=_NOW,
            )
        )
        await uow.commit()
    assert fetching is not None
    assert calculating is not None


def _require_calculation_id(calculation: PerformanceCalculation) -> int:
    if calculation.id is None:
        msg = "calculation id must be assigned"
        raise AssertionError(msg)
    return calculation.id


def _require_score_id(score: Score) -> int:
    if score.id is None:
        msg = "score id must be assigned"
        raise AssertionError(msg)
    return score.id
