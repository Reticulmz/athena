"""score performance calculation request contractを検証するtest module."""

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
    """worker wake呼出し時点のcommit状態を記録するvalue object.

    Attributes:
        score_id (int): wake対象scoreの識別子.
        calculation_id (int): workerへ渡すcalculationの識別子.
        commit_count_at_call (int): wake実行時点で完了しているcommit回数.
    """

    score_id: int
    calculation_id: int
    commit_count_at_call: int


class _CommitCounter(Protocol):
    """commit回数を公開するfactory用Protocol.

    Attributes:
        commit_count (int): testが確認するcommit実行回数.
    """

    commit_count: int


@final
class _WakeRecorder:
    """worker wake要求と要求時のcommit回数を記録するtest double.

    Attributes:
        _factory (_CommitCounter): wake時のcommit回数を参照するfactory.
        calls (list[_WakeCall]): 受信したwake requestの順序付きrecord.
    """

    def __init__(self, factory: _CommitCounter) -> None:
        """commit回数を観測するfactoryを持つrecorderを初期化する.

        Args:
            factory (_CommitCounter): wake request時のcommit回数を提供するfactory.
        """
        self._factory: _CommitCounter = factory
        self.calls: list[_WakeCall] = []

    async def wake_score_calculation(self, *, score_id: int, calculation_id: int) -> None:
        """Score calculationのworker wake要求を記録する.

        Args:
            score_id (int): workerへ渡すscoreの識別子.
            calculation_id (int): workerへ渡すcalculationの識別子.

        Returns:
            None: wake requestとcommit回数をrecordして値を返さず完了する.
        """
        self.calls.append(
            _WakeCall(
                score_id=score_id,
                calculation_id=calculation_id,
                commit_count_at_call=self._factory.commit_count,
            )
        )


@final
class _FailingWake:
    """worker wake失敗を再現するtest double."""

    async def wake_score_calculation(self, *, score_id: int, calculation_id: int) -> None:
        """受信したwake requestを失敗させてerror handlingを検証可能にする.

        Args:
            score_id (int): 失敗対象として受信するscoreの識別子.
            calculation_id (int): 失敗対象として受信するcalculationの識別子.

        Returns:
            None: worker wakeを完了せず呼び出し側へ値を返さない.

        Raises:
            RuntimeError: worker wake失敗を再現するため常に送出する.
        """
        _ = score_id
        _ = calculation_id
        raise RuntimeError("worker wake failed")


@final
class _CountingUnitOfWorkFactory(InMemoryUnitOfWorkFactory):
    """commit回数を記録するin-memory unit of work factory.

    Attributes:
        commit_count (int): commitしたrepository stateの回数.
    """

    commit_count: int

    def __init__(self) -> None:
        """commit回数が0のin-memory factoryを初期化する."""
        super().__init__()
        self.commit_count = 0

    @override
    def commit_state(self, state: InMemoryCommandRepositoryState) -> None:
        """Repository stateをcommitしてcommit回数を加算する.

        Args:
            state (InMemoryCommandRepositoryState): 永続化するin-memory repository state.

        Returns:
            None: 親実装へstateを渡しcommit回数を更新して値を返さず完了する.
        """
        super().commit_state(state)
        self.commit_count += 1

    def reset_commit_count(self) -> None:
        """test対象operationの前にcommit回数を0へ戻す.

        Returns:
            None: 記録済みcommit回数を消去して値を返さず完了する.
        """
        self.commit_count = 0


@final
class _CommitRequiredUnitOfWorkFactory:
    """commit必須のrequest resultを返すunit of work contextを生成するtest double.

    Attributes:
        commit_count (int): contextがcommitを実行した回数.
        rollback_count (int): contextがrollbackを実行した回数.
        score (Score): lookupが返す保存済みscore.
        request_result (ScorePerformanceCalculationRequestResult):
            repositoryが返す固定request result.
    """

    def __init__(
        self,
        *,
        score: Score,
        request_result: ScorePerformanceCalculationRequestResult,
    ) -> None:
        """固定scoreとrequest resultを使うfactoryを初期化する.

        Args:
            score (Score): request対象としてlookupへ返すscore.
            request_result (ScorePerformanceCalculationRequestResult):
                calculation requestで返す固定result.
        """
        self.commit_count: int = 0
        self.rollback_count: int = 0
        self.score: Score = score
        self.request_result: ScorePerformanceCalculationRequestResult = request_result

    def __call__(self) -> _CommitRequiredUnitOfWork:
        """commit状態を観測するunit of work contextを生成する.

        Returns:
            _CommitRequiredUnitOfWork: このfactoryのcounterとfixtureを共有するcontext manager.
        """
        return _CommitRequiredUnitOfWork(self)


@final
class _CommitRequiredUnitOfWork:
    """明示的commitがない操作をrollbackする最小unit of work contextを提供する.

    Attributes:
        _factory (_CommitRequiredUnitOfWorkFactory): commitとrollback回数を記録するfactory.
        _committed (bool): context内でcommit済みかを示すflag.
        scores (_ScoreLookup): 固定scoreを返すread repository.
        score_performance (_CommitRequiredScorePerformanceRepository):
            固定request resultを返すrepository.
    """

    def __init__(self, factory: _CommitRequiredUnitOfWorkFactory) -> None:
        """factoryと固定repositoryを共有するunit of work contextを初期化する.

        Args:
            factory (_CommitRequiredUnitOfWorkFactory): counterとfixtureを所有するfactory.
        """
        self._factory: _CommitRequiredUnitOfWorkFactory = factory
        self._committed: bool = False
        self.scores = _ScoreLookup(factory.score)
        self.score_performance = _CommitRequiredScorePerformanceRepository(factory.request_result)

    async def __aenter__(self) -> _CommitRequiredUnitOfWork:
        """context内で利用するunit of work自身を返す.

        Returns:
            _CommitRequiredUnitOfWork: scoreとperformance repositoryを公開するactive context.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """exceptionまたは未commitのcontextをrollbackして終了する.

        Args:
            exc_type (type[BaseException] | None): context内exceptionのtype. 例外がない場合はNone.
            _exc (BaseException | None): context内で送出されたexception. 例外がない場合はNone.
            _traceback (TracebackType | None): context内exceptionのtraceback. 例外がない場合はNone.

        Returns:
            None: 必要なrollbackを記録して値を返さずcontextを終了する.
        """
        if exc_type is not None or not self._committed:
            await self.rollback()

    async def commit(self) -> None:
        """commit回数を加算してcontextをcommit済みにする.

        Returns:
            None: factoryのcommit counterを更新して値を返さず完了する.
        """
        self._factory.commit_count += 1
        self._committed = True

    async def rollback(self) -> None:
        """rollback回数を加算してcontextを未commit状態に戻す.

        Returns:
            None: factoryのrollback counterを更新して値を返さず完了する.
        """
        self._factory.rollback_count += 1
        self._committed = False


@final
class _ScoreLookup:
    """固定scoreを識別子で返す最小read repositoryを提供するtest double.

    Attributes:
        _score (Score): 一致するIDに対して返す保存済みscore.
    """

    def __init__(self, score: Score) -> None:
        """lookup対象の固定scoreを設定する.

        Args:
            score (Score): get_by_idで返す保存済みscore.
        """
        self._score: Score = score

    async def get_by_id(self, score_id: int) -> Score | None:
        """指定IDが固定scoreと一致する場合だけscoreを返す.

        Args:
            score_id (int): lookupするscoreの識別子.

        Returns:
            Score | None: IDが一致する保存済みscore. 一致しない場合はNone.
        """
        if self._score.id == score_id:
            return self._score
        return None


@final
class _CommitRequiredScorePerformanceRepository:
    """固定request resultを返すscore performance repositoryを提供するtest double.

    Attributes:
        _result (ScorePerformanceCalculationRequestResult):
            calculation requestに対して返す固定result.
    """

    def __init__(self, result: ScorePerformanceCalculationRequestResult) -> None:
        """Calculation requestへ返す固定resultを設定する.

        Args:
            result (ScorePerformanceCalculationRequestResult):
                repository methodが返すrequest result.
        """
        self._result: ScorePerformanceCalculationRequestResult = result

    async def create_or_reuse_calculation(
        self,
        command: CreateScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationRequestResult:
        """入力commandにかかわらず固定calculation request resultを返す.

        Args:
            command (CreateScorePerformanceCalculation):
                interface適合のため受信するcalculation command.

        Returns:
            ScorePerformanceCalculationRequestResult: constructorで設定した固定request result.
        """
        _ = command
        return self._result


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED])
async def test_eligible_passed_score_creates_calculation_row_and_wakes_after_commit(
    status: BeatmapRankStatus,
) -> None:
    """Eligible passed scoreがcommit後にcalculationを作成してworkerをwakeする契約を検証する.

    rankedまたはapprovedのpassed scoreを保存してrequestし queued calculationが1件作成されることと
    wake時点でcommit済みであることを確認する.

    Args:
        status (BeatmapRankStatus): eligible scoreへ設定するbeatmap rank status.

    Returns:
        None: request outcomeとqueued calculationとcommit後のwake recordを検証して完了する.
    """
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
    """Duplicate eligible requestがpending calculationを再利用してworkerをwakeする契約を検証する.

    同一eligible scoreへ2回requestし 2回目が既存pending rowを使い新しいrowを作らずworkerをwakeする
    ことを確認する.

    Returns:
        None: createdとreused outcomeと単一rowと2件のwake recordを検証して完了する.
    """
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
    """Worker wake失敗がdurable calculation rowをrollbackしないrequest契約を検証する.

    eligible scoreを保存して常に失敗するwake adapterでrequestし wake failureをresultへ記録しながら
    queued calculationをcommit済みのまま保持することを確認する.

    Returns:
        None: created outcome, wake failure metadata, 永続化されたqueued calculationを
            検証して完了する.
    """
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
    """Matching terminal calculationがrequestをno-opにしてworkerをwakeしない契約を検証する.

    completedまたはunavailableのcurrent calculationを持つscoreをrequestする.
    rowを再利用してcommitもwakeも行わないことを確認する.

    Args:
        terminal_state (PerformanceCalculationState): current calculationへ設定するterminal state.

    Returns:
        None: already current outcomeと既存rowとcommitおよびwake不在を検証して完了する.
    """
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
    """Stale completed provenanceがcurrent calculationを保持したreplacementを作る契約を検証する.

    旧calculator versionでcompletedにしたcurrent calculationをrequestする.
    新しいqueued replacementを作って旧current rowを上書きせずworkerをwakeすることを確認する.

    Returns:
        None: replacement outcomeと2件のrowと維持されるold current calculationを検証して完了する.
    """
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
    """commit必須のreused replacement mutationがwake前にcommitされる契約を検証する.

    requires commitのreused replacement resultを返すfake repositoryでrequestする.
    rollbackせずcommitした後にworker wakeが記録されることを確認する.

    Returns:
        None: reused replacement outcomeとcommit回数とrollback不在とwake recordを検証して完了する.
    """
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
    """scope外scoreがperformance rowもworker wakeも作らずskipされるrequest契約を検証する.

    対象外beatmap statusまたはfailed scoreを保存してrequestする.
    eligibility reasonを返して既存scoreだけを維持することを確認する.

    Args:
        status (BeatmapRankStatus): scoreへ設定するbeatmap rank status.
        passed (bool): scoreをpassedとして扱うか.
        eligibility_reason (str): request resultに期待するskip reason.

    Returns:
        None: skipped outcomeとreasonとperformance rowおよびwake不在を検証して完了する.
    """
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
    """存在しないscore requestがperformance rowもworker wakeも作らない契約を検証する.

    scoreを保存せず未存在IDをrequestし score not found outcomeとcalculation未作成を確認する.

    Returns:
        None: missing score outcomeとcommitとperformance rowとwake不在を検証して完了する.
    """
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
    """Request eligibility条件を制御できる未永続化scoreを組み立てる.

    Args:
        status (BeatmapRankStatus | str | None): submission時のbeatmap status.
            Noneの場合はstatus未設定にする.
        passed (bool): scoreをpassedとして扱うか.
        online_checksum (str): scoreへ設定するonline checksum.

    Returns:
        Score: 指定eligibility条件とfixed vanilla metadataを持つ未永続化score.

    Raises:
        ValueError: statusがBeatmapRankStatusへ変換できない値の場合.
    """
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
    """指定current状態を持つqueued performance calculationを組み立てる.

    Args:
        calculation_id (int): calculationへ設定する識別子.
        score_id (int): calculationを関連付けるscoreの識別子.
        is_current (bool): calculationをcurrentとして扱うか.

    Returns:
        PerformanceCalculation: performance値が未計算のqueued calculation.
    """
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
    """固定calculator provenanceを持つcalculation request commandを組み立てる.

    Args:
        score_id (int): calculationをrequestするscoreの識別子.

    Returns:
        RequestPerformanceCalculationCommand: fixed calculator name, version, request時刻を持つ
            command.
    """
    return RequestPerformanceCalculationCommand(
        score_id=score_id,
        calculator_name=_CALCULATOR_NAME,
        calculator_version=_CALCULATOR_VERSION,
        requested_at=_NOW,
    )


async def _persist_score(factory: _CountingUnitOfWorkFactory, score: Score) -> int:
    """Test scoreをin-memory persistenceへ保存して識別子を返す.

    Args:
        factory (_CountingUnitOfWorkFactory): scoreを保存してcommit回数を記録するfactory.
        score (Score): 永続化するtest score.

    Returns:
        int: 保存後に割り当てられたscore ID.
    """
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
    """score用のpending performance calculationを作成して識別子を返す.

    Args:
        factory (_CountingUnitOfWorkFactory): calculationを保存してcommit回数を記録するfactory.
        score_id (int): calculationを関連付けるscoreの識別子.
        calculator_version (str): calculationへ設定するcalculator version.

    Returns:
        int: 永続化済みpending calculationの識別子.
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


async def _finalize_calculation(
    factory: _CountingUnitOfWorkFactory,
    *,
    calculation_id: int,
    state: PerformanceCalculationState,
    calculator_version: str = _CALCULATOR_VERSION,
) -> None:
    """Pending calculationを指定terminal stateへ遷移してcommitする.

    Args:
        factory (_CountingUnitOfWorkFactory): calculation stateを保存してcommit回数を
            記録するfactory.
        calculation_id (int): terminal stateへ遷移するcalculationの識別子.
        state (PerformanceCalculationState): COMPLETEDまたはUNAVAILABLEのterminal state.
        calculator_version (str): final resultへ設定するcalculator version.

    Returns:
        None: terminal stateを保存してcommitした後に値を返さず完了する.

    Raises:
        ValueError: stateがtestで扱うterminal stateではない場合.
    """
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
    """in-memory factoryに保存されたperformance calculation row数を返す.

    Args:
        factory (_CountingUnitOfWorkFactory): snapshotからrow数を取得するfactory.

    Returns:
        int: 保存済みperformance calculationの件数.
    """
    return len(factory.snapshot().performance_calculations_by_id)


def _require_calculation_id(calculation: PerformanceCalculation) -> int:
    """永続化済みcalculationから必須の識別子を取得する.

    Args:
        calculation (PerformanceCalculation): 識別子が割り当て済みであるべきcalculation.

    Returns:
        int: calculationの永続化済み識別子.

    Raises:
        AssertionError: calculation IDが未割り当ての場合.
    """
    if calculation.id is None:
        msg = "calculation id must be assigned"
        raise AssertionError(msg)
    return calculation.id
