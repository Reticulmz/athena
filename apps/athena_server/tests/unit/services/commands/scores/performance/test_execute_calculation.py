"""score performance計算work実行の状態遷移と副作用を検証する."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, final, override

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
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
    """完了signal送信時点のpayloadとcommit状態を記録する値.

    Attributes:
        payload (PerformanceCompletionSignalPayload): 送信対象の計算完了通知.
        commit_count_at_call (int): signal送信時点のcommit回数.
    """

    payload: PerformanceCompletionSignalPayload
    commit_count_at_call: int


@final
class _CountingUnitOfWorkFactory(InMemoryUnitOfWorkFactory):
    """commit回数を数えるin-memory Unit of Work factory.

    Attributes:
        commit_count (int): stateをcommitした回数.
    """

    commit_count: int

    def __init__(self) -> None:
        """空のin-memory状態とcommit回数を初期化する."""
        super().__init__()
        self.commit_count = 0

    @override
    def commit_state(self, state: InMemoryCommandRepositoryState) -> None:
        """親factoryへ状態をcommitし, commit回数を加算する.

        Args:
            state (InMemoryCommandRepositoryState): 永続化するin-memory repository状態.

        Returns:
            None: 親factoryのstate更新と回数記録を行い, 値を返さずに完了する.
        """
        super().commit_state(state)
        self.commit_count += 1

    def reset_commit_count(self) -> None:
        """後続assertion用にcommit回数を0へ戻す.

        Returns:
            None: commit回数を初期化して値を返さずに完了する.
        """
        self.commit_count = 0


@final
class _FileProvider:
    """固定したbeatmap file結果と呼び出し時の状態を検証するtest double.

    Attributes:
        _result (PerformanceBeatmapFileResult): provide呼び出しへ返すfile取得結果.
        _factory (_CountingUnitOfWorkFactory | None): 期待状態を確認する任意のfactory.
        _calculation_id (int | None): 期待状態を確認する計算識別子.
        _expected_state_at_call (PerformanceCalculationState | None): provide時に必要な計算状態.
        queries (list[PerformanceBeatmapFileQuery]): 受け取ったfile要求の記録.
    """

    def __init__(
        self,
        result: PerformanceBeatmapFileResult,
        *,
        factory: _CountingUnitOfWorkFactory | None = None,
        calculation_id: int | None = None,
        expected_state_at_call: PerformanceCalculationState | None = None,
    ) -> None:
        """返却結果と任意の状態確認条件を設定する.

        Args:
            result (PerformanceBeatmapFileResult): provide呼び出しへ返す固定結果.
            factory (_CountingUnitOfWorkFactory | None): 計算状態をsnapshotで確認する任意のfactory.
            calculation_id (int | None): 確認対象の計算識別子.
            expected_state_at_call (PerformanceCalculationState | None): provide前に期待する
                計算状態.
        """
        self._result = result
        self._factory = factory
        self._calculation_id = calculation_id
        self._expected_state_at_call = expected_state_at_call
        self.queries: list[PerformanceBeatmapFileQuery] = []

    async def provide(
        self,
        query: PerformanceBeatmapFileQuery,
    ) -> PerformanceBeatmapFileResult:
        """要求を記録し, 必要なら計算状態を確認して固定結果を返す.

        Args:
            query (PerformanceBeatmapFileQuery): beatmap fileを要求するquery.

        Returns:
            PerformanceBeatmapFileResult: 初期化時に設定したfile取得結果.
        """
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
    """固定した計算結果と呼び出し時の状態を検証するcalculator test double.

    Attributes:
        _result (PerformanceCalculatorCompleted | PerformanceCalculatorUnavailable):
            calculate呼び出しへ返す結果.
        _factory (_CountingUnitOfWorkFactory | None): 期待状態を確認する任意のfactory.
        _calculation_id (int | None): 期待状態を確認する計算識別子.
        _calculator_version (str): calculator identityとして返すversion.
        _expected_state_at_call (PerformanceCalculationState | None): calculate時に必要な計算状態.
        inputs (list[PerformanceCalculatorInput]): 受け取った計算入力の記録.
    """

    def __init__(
        self,
        result: PerformanceCalculatorCompleted | PerformanceCalculatorUnavailable,
        *,
        factory: _CountingUnitOfWorkFactory | None = None,
        calculation_id: int | None = None,
        calculator_version: str = _CALCULATOR_VERSION,
        expected_state_at_call: PerformanceCalculationState | None = None,
    ) -> None:
        """返却結果, identity, 任意の状態確認条件を設定する.

        Args:
            result (PerformanceCalculatorCompleted | PerformanceCalculatorUnavailable):
                calculate呼び出しへ返す固定結果.
            factory (_CountingUnitOfWorkFactory | None): 計算状態をsnapshotで確認する任意のfactory.
            calculation_id (int | None): 確認対象の計算識別子.
            calculator_version (str): calculator identityとして返すversion.
            expected_state_at_call (PerformanceCalculationState | None): calculate前に期待する
                計算状態.
        """
        self._result = result
        self._factory = factory
        self._calculation_id = calculation_id
        self._calculator_version = calculator_version
        self._expected_state_at_call = expected_state_at_call
        self.inputs: list[PerformanceCalculatorInput] = []

    def calculator_name(self) -> str:
        """testで固定したcalculator名を返す.

        Returns:
            str: score performance計算に使用するcalculator名.
        """
        return _CALCULATOR_NAME

    def calculator_version(self) -> str:
        """設定済みcalculator versionを返す.

        Returns:
            str: 初期化時に設定したcalculator version.
        """
        return self._calculator_version

    def calculate(
        self,
        input_data: PerformanceCalculatorInput,
    ) -> PerformanceCalculatorCompleted | PerformanceCalculatorUnavailable:
        """入力を記録し, 必要なら状態を確認して固定結果を返す.

        Args:
            input_data (PerformanceCalculatorInput): scoreとosu file内容を含む計算入力.

        Returns:
            PerformanceCalculatorCompleted | PerformanceCalculatorUnavailable: 初期化時に設定した
                計算結果.
        """
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
    """計算完了signalと送信時のcommit順序を記録するtest double.

    Attributes:
        _factory (_CountingUnitOfWorkFactory): signal送信時のcommit回数を参照するfactory.
        calls (list[_SignalCall]): 送信したpayloadとcommit時点の記録.
    """

    def __init__(self, factory: _CountingUnitOfWorkFactory) -> None:
        """commit状態を確認するfactoryを設定する.

        Args:
            factory (_CountingUnitOfWorkFactory): signal送信時のcommit回数を提供するfactory.
        """
        self._factory = factory
        self.calls: list[_SignalCall] = []

    async def notify(self, payload: PerformanceCompletionSignalPayload) -> None:
        """完了payloadと送信時のcommit回数を記録する.

        Args:
            payload (PerformanceCompletionSignalPayload): 完了状態を通知するpayload.

        Returns:
            None: signal送信記録を追加して値を返さずに完了する.
        """
        self.calls.append(
            _SignalCall(
                payload=payload,
                commit_count_at_call=self._factory.commit_count,
            )
        )

    async def wait(self, score_id: int, timeout: timedelta) -> bool:
        """待機要求を成功として扱わずFalseを返す.

        Args:
            score_id (int): 完了を待つscoreの識別子.
            timeout (timedelta): 完了通知を待つ最大時間.

        Returns:
            bool: 常にFalse. このtest doubleは実際にsignalを待機しない.
        """
        _ = score_id
        _ = timeout
        return False


@pytest.mark.asyncio
async def test_execute_calculation_claims_calculates_commits_and_signals_completion() -> None:
    """計算workをclaimし, 完了保存後にsignalを送る契約を検証する.

    pending計算, ready file, 成功calculatorを用意し, 状態遷移とprojection更新を確認する.
    stats更新とcommit後signalも確認する.

    Returns:
        None: 完了計算, projection, stats, signal送信順序を検証して完了する.
    """
    factory = _CountingUnitOfWorkFactory()
    score_id = await _persist_score(factory, score := _score())
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
    """置換計算のPP低下時に次点scoreでprojectionを再構築する契約を検証する.

    現在bestより低い置換PPと次点scoreを用意する.
    current計算を置換しつつprojectionとstatsは次点へ戻ることを確認する.

    Returns:
        None: current計算, best projection, stats projectionの再構築を検証して完了する.
    """
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
    """置換計算が利用不能な場合に次点scoreでprojectionを再構築する契約を検証する.

    現在bestの置換計算をcalculator失敗にする.
    currentはunavailableでもprojectionとstatsは次点へ戻ることを確認する.

    Returns:
        None: unavailable current計算と次点へのprojection再構築を検証して完了する.
    """
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
    """一時的なfile入力待ちをFETCHING_FILEのまま保持する契約を検証する.

    pending file結果を返し, calculator実行, unavailable確定, 完了signalを行わないことを確認する.

    Returns:
        None: pending結果, 保持状態, signal未送信を検証して完了する.
    """
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
    """FETCHING_FILE状態の計算をready file到着後に再試行できる契約を検証する.

    最初にpending fileで待機状態へ遷移させる.
    次のclaimで計算完了, commit, signal送信へ進むことを確認する.

    Returns:
        None: 再試行後の完了計算, calculator入力, signalを検証して完了する.
    """
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
    """CALCULATING状態の計算を再試行して完了できる契約を検証する.

    計算をCALCULATINGまで進めてから再実行する.
    file取得とcalculator実行後に完了signalが送られることを確認する.

    Returns:
        None: CALCULATINGからの完了状態, commit回数, signalを検証して完了する.
    """
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
    """恒久的なfile取得失敗をunavailableへ確定しsignalする契約を検証する.

    FAILED file結果を返す.
    calculatorを呼ばずに計算状態, 理由, commit後signalを確定することを確認する.

    Returns:
        None: unavailable計算, file失敗理由, signal送信を検証して完了する.
    """
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
    """calculator失敗をfile provenance付きunavailableへ確定する契約を検証する.

    ready fileと利用不能calculator結果を用意する.
    file attachment情報を保って完了signalすることを確認する.

    Returns:
        None: calculator失敗理由, file provenance, signal送信を検証して完了する.
    """
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
    """claimを取得できないworkを確定もsignalもせずに終える契約を検証する.

    存在しない計算識別子を指定する.
    file取得, calculator実行, commit, signal送信が発生しないことを確認する.

    Returns:
        None: claim未取得結果と副作用なしを検証して完了する.
    """
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
    """存在しないscoreをunavailableへ確定して報告する契約を検証する.

    scoreが保存されていないpending計算を実行する.
    file取得なしでscore_not_found理由とsignalが残ることを確認する.

    Returns:
        None: score未検出結果, unavailable状態, signal送信を検証して完了する.
    """
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
    """試験用doubleを接続した計算実行use caseを構築する.

    Args:
        factory (_CountingUnitOfWorkFactory): score, 計算, projection状態を所有するfactory.
        file_provider (_FileProvider): beatmap file結果を返すprovider.
        calculator (_Calculator): 成功または利用不能結果を返すcalculator.
        completion_signal (_CompletionSignal): 完了通知を記録するsignal collaborator.

    Returns:
        ExecutePerformanceCalculationUseCase: 固定claim timeoutを持つ設定済みuse case.
    """
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
    """計算workをclaimして実行するcommandを構築する.

    Args:
        calculation_id (int): 実行対象のperformance calculation識別子.
        claimed_at (datetime): workerがclaimを試みる時刻.

    Returns:
        ExecutePerformanceCalculationCommand: 固定claim ownerを持つ実行command.
    """
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
    """projection更新を検証するためのranked scoreを構築する.

    Args:
        score (int): score値.
        accuracy (float): scoreのaccuracy値.
        online_checksum (str): scoreを一意にするonline checksum.
        submitted_at (datetime): scoreの提出時刻.

    Returns:
        Score: 永続化前のranked osu score.
    """
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
        beatmap_status_at_submission=BeatmapRankStatus.RANKED,
        leaderboard_eligible_at_submission=True,
    )


def _ready_file() -> PerformanceBeatmapFileReady:
    """計算可能なosu fileとprovenanceを持つready結果を構築する.

    Returns:
        PerformanceBeatmapFileReady: 固定beatmap, attachment, blob情報を持つfile結果.
    """
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
    """file取得待ちを表すpending結果を構築する.

    Returns:
        PerformanceBeatmapFilePending: PENDING_FETCH状態を持つ一時的なfile結果.
    """
    return PerformanceBeatmapFilePending(
        beatmap_id=2000,
        reason=PerformanceBeatmapFilePendingReason.OSU_FILE_FETCH_PENDING,
        metadata_status=BeatmapFetchState.FRESH,
        file_status=BeatmapFileState.PENDING_FETCH,
        mirror_reason=None,
    )


def _unavailable_file() -> PerformanceBeatmapFileUnavailable:
    """恒久的なfile取得失敗を表すunavailable結果を構築する.

    Returns:
        PerformanceBeatmapFileUnavailable: FAILED状態とmirror理由を持つfile結果.
    """
    return PerformanceBeatmapFileUnavailable(
        beatmap_id=2000,
        reason=PerformanceBeatmapFileUnavailableReason.OSU_FILE_FETCH_FAILED,
        metadata_status=BeatmapFetchState.FRESH,
        file_status=BeatmapFileState.FAILED,
        mirror_reason="fetch failed",
    )


async def _persist_score(factory: _CountingUnitOfWorkFactory, score: Score) -> int:
    """scoreと対応beatmap snapshotをin-memory状態へ保存する.

    Args:
        factory (_CountingUnitOfWorkFactory): 保存先のin-memory Unit of Work factory.
        score (Score): 永続化するscore.

    Returns:
        int: 永続化後にscoreへ割り当てられた識別子.
    """
    async with factory() as uow:
        await uow.beatmaps.save_beatmapset_snapshot(_beatmapset_for_score(score))
        created = await uow.scores.create(score)
        await uow.commit()
    assert created.id is not None
    return created.id


def _beatmapset_for_score(score: Score) -> BeatmapSet:
    """scoreのbeatmap参照を満たすsnapshotを構築する.

    Args:
        score (Score): beatmap識別子, checksum, rank状態を提供するscore.

    Returns:
        BeatmapSet: score保存前に必要な単一beatmapのsnapshot.
    """
    official_status = score.beatmap_status_at_submission
    assert official_status is not None
    beatmap = Beatmap(
        id=score.beatmap_id,
        beatmapset_id=score.beatmap_id,
        checksum_md5=score.beatmap_checksum,
        mode=BeatmapMode.OSU,
        version="Test",
        total_length=None,
        hit_length=None,
        max_combo=None,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=official_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=None,
        next_refresh_at=None,
    )
    return BeatmapSet(
        id=score.beatmap_id,
        artist="artist",
        title="title",
        creator="creator",
        artist_unicode=None,
        title_unicode=None,
        official_status=official_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=None,
        next_refresh_at=None,
    )


async def _create_pending_calculation(
    factory: _CountingUnitOfWorkFactory,
    *,
    score_id: int,
    calculator_version: str = _CALCULATOR_VERSION,
) -> int:
    """指定score用のpending performance calculationを作成する.

    Args:
        factory (_CountingUnitOfWorkFactory): 計算状態を保存するfactory.
        score_id (int): 計算対象scoreの識別子.
        calculator_version (str): 作成する計算に記録するcalculator version.

    Returns:
        int: 作成または再利用したperformance calculationの識別子.
    """
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
    """scoreの現在計算を作成して完了状態へ保存する.

    Args:
        factory (_CountingUnitOfWorkFactory): 計算状態を保存するfactory.
        score_id (int): 完了計算を関連付けるscoreの識別子.
        pp (Decimal): 完了計算に保存するperformance point値.
        calculator_version (str): 完了計算に保存するcalculator version.

    Returns:
        int: 完了状態へ遷移したperformance calculationの識別子.
    """
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
    """既存scoreのcalculator version置換用pending計算を作成する.

    Args:
        factory (_CountingUnitOfWorkFactory): 計算状態を保存するfactory.
        score_id (int): 置換計算を関連付けるscoreの識別子.
        calculator_version (str): 置換計算に記録する新しいcalculator version.

    Returns:
        int: 置換用pending performance calculationの識別子.
    """
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
    """既存best scoreを表すbeatmap performance projectionを保存する.

    Args:
        factory (_CountingUnitOfWorkFactory): projectionを保存するfactory.
        score (Score): projectionのscore, accuracy, 提出時刻を提供するscore.
        calculation_id (int): scoreへ関連付ける完了計算の識別子.
        pp (Decimal): projectionに保存するperformance point値.

    Returns:
        None: best projectionを保存して値を返さずに完了する.
    """
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
    """pending計算をFETCHING_FILE経由でCALCULATINGへ進める.

    Args:
        factory (_CountingUnitOfWorkFactory): 計算状態を更新するfactory.
        calculation_id (int): 遷移対象のperformance calculation識別子.

    Returns:
        None: 2段階の状態遷移を保存して値を返さずに完了する.
    """
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
    """永続化済みperformance calculationの識別子を返す.

    Args:
        calculation (PerformanceCalculation): 識別子の割り当てを確認する計算.

    Returns:
        int: Noneではないperformance calculation識別子.

    Raises:
        AssertionError: calculationへ識別子が割り当てられていない場合.
    """
    if calculation.id is None:
        msg = "calculation id must be assigned"
        raise AssertionError(msg)
    return calculation.id


def _require_score_id(score: Score) -> int:
    """永続化済みscoreの識別子を返す.

    Args:
        score (Score): 識別子の割り当てを確認するscore.

    Returns:
        int: Noneではないscore識別子.

    Raises:
        AssertionError: scoreへ識別子が割り当てられていない場合.
    """
    if score.id is None:
        msg = "score id must be assigned"
        raise AssertionError(msg)
    return score.id
