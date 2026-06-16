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
from osu_server.infrastructure.performance import (
    PerformanceCalculatorCompleted,
    PerformanceCalculatorInput,
    PerformanceCalculatorUnavailable,
    PerformanceCalculatorUnavailableReason,
)
from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
    PerformanceCompletionSignalPayload,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    CreateScorePerformanceCalculation,
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
    def __init__(self, result: PerformanceBeatmapFileResult) -> None:
        self._result = result
        self.queries: list[PerformanceBeatmapFileQuery] = []

    async def provide(
        self,
        query: PerformanceBeatmapFileQuery,
    ) -> PerformanceBeatmapFileResult:
        self.queries.append(query)
        return self._result


@final
class _Calculator:
    def __init__(
        self,
        result: PerformanceCalculatorCompleted | PerformanceCalculatorUnavailable,
    ) -> None:
        self._result = result
        self.inputs: list[PerformanceCalculatorInput] = []

    def calculator_name(self) -> str:
        return _CALCULATOR_NAME

    def calculator_version(self) -> str:
        return _CALCULATOR_VERSION

    def calculate(
        self,
        input_data: PerformanceCalculatorInput,
    ) -> PerformanceCalculatorCompleted | PerformanceCalculatorUnavailable:
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
    file_provider = _FileProvider(_ready_file())
    calculator = _Calculator(
        PerformanceCalculatorCompleted(
            pp=Decimal("123.456789"),
            star_rating=Decimal("5.43210"),
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
    assert factory.commit_count == 2
    assert file_provider.queries == [PerformanceBeatmapFileQuery(score.beatmap_id)]
    assert len(calculator.inputs) == 1
    assert calculator.inputs[0].score == replace(score, id=score_id)
    assert calculator.inputs[0].osu_file_bytes == b"osu file bytes"
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
    assert result.calculation.state is PerformanceCalculationState.QUEUED
    assert result.pending_reason == PerformanceBeatmapFilePendingReason.OSU_FILE_FETCH_PENDING
    assert result.signal_notified is False
    assert factory.commit_count == 1
    assert calculator.inputs == []
    assert completion_signal.calls == []
    async with factory() as uow:
        current = await uow.score_performance.get_current_for_score(score_id)
    assert current is not None
    assert current.state is PerformanceCalculationState.QUEUED
    assert current.unavailable_reason is None


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
        )
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
    assert factory.commit_count == 2
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


def _command(*, calculation_id: int) -> ExecutePerformanceCalculationCommand:
    return ExecutePerformanceCalculationCommand(
        calculation_id=calculation_id,
        claim_owner=_CLAIM_OWNER,
        claimed_at=_NOW,
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
        beatmap_status_at_submission=BeatmapRankStatus.RANKED.value,
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
) -> int:
    async with factory() as uow:
        result = await uow.score_performance.create_or_reuse_calculation(
            CreateScorePerformanceCalculation(
                score_id=score_id,
                calculator_name=_CALCULATOR_NAME,
                calculator_version=_CALCULATOR_VERSION,
                formula_profile=FormulaProfile.VANILLA_RANKED,
                requested_at=_NOW,
            )
        )
        await uow.commit()
    return _require_calculation_id(result.calculation)


def _require_calculation_id(calculation: PerformanceCalculation) -> int:
    if calculation.id is None:
        msg = "calculation id must be assigned"
        raise AssertionError(msg)
    return calculation.id
