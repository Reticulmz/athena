"""score performance再計算batch作成の契約を検証する."""

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
    """worker起床要求時点のcommit状態を記録する値.

    Attributes:
        batch_id (int): 起床対象の再計算batch識別子.
        commit_count_at_call (int): 起床要求を行った時点のcommit回数.
    """

    batch_id: int
    commit_count_at_call: int


@final
class _CalculatorIdentity:
    """testで固定するperformance calculatorの識別情報を提供する."""

    def calculator_name(self) -> str:
        """固定したcalculator名を返す.

        Returns:
            str: testで使用するcalculator名.
        """
        return _CALCULATOR_NAME

    def calculator_version(self) -> str:
        """固定したcalculator versionを返す.

        Returns:
            str: testで使用するcalculator version.
        """
        return _CALCULATOR_VERSION


@final
class _QueryRepository:
    """候補選択結果を固定して記録するquery repository test double.

    Attributes:
        _result (ScorePerformanceRecalculationCandidateResult): 選択時に返す候補結果.
        selections (list[ScorePerformanceCandidateSelection]): 受け取った候補選択条件の記録.
    """

    def __init__(self, result: ScorePerformanceRecalculationCandidateResult) -> None:
        """返却する候補選択結果を設定する.

        Args:
            result (ScorePerformanceRecalculationCandidateResult): testで返す候補と理由集計.
        """
        self._result = result
        self.selections: list[ScorePerformanceCandidateSelection] = []

    async def select_recalculation_candidates(
        self,
        selection: ScorePerformanceCandidateSelection,
    ) -> ScorePerformanceRecalculationCandidateResult:
        """選択条件を記録して設定済み候補を返す.

        Args:
            selection (ScorePerformanceCandidateSelection): use caseが要求した候補選択条件.

        Returns:
            ScorePerformanceRecalculationCandidateResult: 初期化時に設定した候補選択結果.
        """
        self.selections.append(selection)
        return self._result

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        """現在計算を持たない状態を返す.

        Args:
            score_id (int): 参照対象scoreの識別子.

        Returns:
            PerformanceCalculation | None: 常にNone. batch作成は既存計算を参照しないことを表す.
        """
        _ = score_id
        return None


@final
class _UnitOfWorkFactory:
    """commitと生成batchを記録するUnit of Work factory test double.

    Attributes:
        open_count (int): Unit of Workを開いた回数.
        commit_count (int): commitを完了した回数.
        rollback_count (int): rollbackを実行した回数.
        created_batches (list[CreateScorePerformanceRecalculationBatch]): repositoryへ渡した
            batch作成command.
    """

    def __init__(self) -> None:
        """空の呼び出し記録を持つfactoryを初期化する."""
        self.open_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.created_batches: list[CreateScorePerformanceRecalculationBatch] = []

    def __call__(self) -> _UnitOfWork:
        """commit記録を共有する新しいUnit of Workを開く.

        Returns:
            _UnitOfWork: このfactoryの記録へ反映するcontext manager.
        """
        self.open_count += 1
        return _UnitOfWork(self)


@final
class _UnitOfWork:
    """再計算batch作成commandを記録する非同期Unit of Work test double.

    Attributes:
        _factory (_UnitOfWorkFactory): commit, rollback, batch作成を記録する共有factory.
        _committed (bool): context終了時のrollback要否を示すcommit状態.
        score_performance (_ScorePerformanceCommandRepository): 再計算batchを作成する
            command repository.
    """

    def __init__(self, factory: _UnitOfWorkFactory) -> None:
        """共有factoryを使うUnit of Workを初期化する.

        Args:
            factory (_UnitOfWorkFactory): 状態記録を所有するfactory.
        """
        self._factory = factory
        self._committed = False
        self.score_performance = _ScorePerformanceCommandRepository(factory)

    async def __aenter__(self) -> _UnitOfWork:
        """非同期context内でこのUnit of Workを返す.

        Returns:
            _UnitOfWork: repository操作に使用する現在のinstance.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """未commitまたは例外終了時にrollbackする.

        Args:
            exc_type (type[BaseException] | None): contextから渡される例外型.
            _exc (BaseException | None): contextから渡される例外instance.
            _traceback (TracebackType | None): contextから渡されるtraceback.

        Returns:
            None: rollback要否を処理して値を返さずに完了する.
        """
        if exc_type is not None or not self._committed:
            await self.rollback()

    async def commit(self) -> None:
        """commit回数を記録してrollback不要な状態へ遷移する.

        Returns:
            None: factoryのcommit状態を更新して値を返さずに完了する.
        """
        self._factory.commit_count += 1
        self._committed = True

    async def rollback(self) -> None:
        """rollback回数を記録して未commit状態へ戻す.

        Returns:
            None: factoryのrollback状態を更新して値を返さずに完了する.
        """
        self._factory.rollback_count += 1
        self._committed = False


@final
class _ScorePerformanceCommandRepository:
    """再計算batch作成commandをfactoryへ記録するrepository test double.

    Attributes:
        _factory (_UnitOfWorkFactory): 作成commandを記録する共有factory.
    """

    def __init__(self, factory: _UnitOfWorkFactory) -> None:
        """作成commandを記録するfactoryを設定する.

        Args:
            factory (_UnitOfWorkFactory): batch作成記録を所有するfactory.
        """
        self._factory = factory

    async def create_recalculation_batch(
        self,
        command: CreateScorePerformanceRecalculationBatch,
    ) -> PerformanceRecalculationBatch:
        """作成commandを記録してpending batchを返す.

        Args:
            command (CreateScorePerformanceRecalculationBatch): 保存対象のfilter, 理由集計,
                work itemを持つcommand.

        Returns:
            PerformanceRecalculationBatch: 記録順を識別子にしたpending batch.
        """
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
    """再計算worker起床要求とcommit順序を記録するtest double.

    Attributes:
        _factory (_UnitOfWorkFactory): 起床時点のcommit回数を提供するfactory.
        calls (list[_WakeCall]): 起床対象batchとcommit時点の記録.
    """

    def __init__(self, factory: _UnitOfWorkFactory) -> None:
        """commit状態を確認するfactoryを設定する.

        Args:
            factory (_UnitOfWorkFactory): 起床要求時のcommit回数を参照するfactory.
        """
        self._factory = factory
        self.calls: list[_WakeCall] = []

    async def wake_recalculation_batch(self, *, batch_id: int) -> None:
        """worker起床要求とその時点のcommit回数を記録する.

        Args:
            batch_id (int): 起床対象の再計算batch識別子.

        Returns:
            None: 起床要求を記録して値を返さずに完了する.
        """
        self.calls.append(
            _WakeCall(
                batch_id=batch_id,
                commit_count_at_call=self._factory.commit_count,
            )
        )


def _candidate_result(
    *candidates: ScorePerformanceRecalculationCandidate,
) -> ScorePerformanceRecalculationCandidateResult:
    """候補列から理由別件数を含む選択結果を構築する.

    Args:
        *candidates (ScorePerformanceRecalculationCandidate): 再計算対象として返す候補.

    Returns:
        ScorePerformanceRecalculationCandidateResult: 候補列と理由別件数を持つ選択結果.
    """
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
    """既存計算を持たない再計算候補を構築する.

    Args:
        score_id (int): 再計算対象scoreの識別子.
        reason (RecalculationCandidateReason): 再計算が必要な理由.

    Returns:
        ScorePerformanceRecalculationCandidate: 現在計算識別子なしの候補.
    """
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
    """試験用doubleを接続した再計算batch作成use caseを構築する.

    Args:
        query_repository (_QueryRepository): 候補選択結果を返すquery repository.
        factory (_UnitOfWorkFactory): batch作成とtransaction状態を記録するfactory.
        wake (_WakeRecorder | None): worker起床要求を記録する任意のcollaborator.

    Returns:
        CreatePerformanceRecalculationBatchUseCase: testで実行する設定済みuse case.
    """
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
    """候補選択scopeを表す再計算batch作成commandを構築する.

    Args:
        mode (CreatePerformanceRecalculationBatchMode): dry runまたはbatch保存の実行方法.
        score_id (int | None): 単一scoreへ絞る任意の識別子.
        beatmap_id (int | None): beatmapへ絞る任意の識別子.
        user_id (int | None): userへ絞る任意の識別子.
        ruleset (Ruleset | None): rulesetへ絞る任意の値.
        limit (int | None): 取得候補数の上限.
        full_scope (bool): 狭いfilterなしの実行を明示的に許可するか.
        include_unavailable (bool): 利用不能な計算も候補へ含めるか.

    Returns:
        CreatePerformanceRecalculationBatchCommand: 固定request時刻を持つ作成command.
    """
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
    """候補集計だけを返すdry runが副作用を起こさない契約を検証する.

    2種類の候補を用意し, Unit of Workを開かずworkerも起こさない結果を確認する.

    Returns:
        None: dry runの集計結果と副作用なしを検証して完了する.
    """
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
    """executeがbatchのfilter, provenance, work itemを保存してcommitする契約を検証する.

    複数理由の候補と絞り込み条件を用意し, 保存内容, calculator情報, commit後のworker起床を確認する.

    Returns:
        None: 保存済みbatch内容, commit, worker起床順序を検証して完了する.
    """
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
    """狭いfilterなしのexecuteをfull scope承認なしで拒否する契約を検証する.

    score, beatmap, userのfilterを持たないcommandを渡す.
    候補選択, 保存, worker起床がないことを確認する.

    Returns:
        None: 拒否理由と副作用なしを検証して完了する.
    """
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
    """利用不能計算を含める指定をfilterと候補選択へ保持する契約を検証する.

    UNAVAILABLE候補を用意し, dry run結果とquery repositoryへ同じ指定が渡ることを確認する.

    Returns:
        None: filter値と候補選択条件を検証して完了する.
    """
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
    """候補数上限がfull scope安全確認の代替にならない契約を検証する.

    同じlimitで未承認executeを拒否し, 承認済みdry runだけが候補選択することを確認する.

    Returns:
        None: safety拒否と候補上限の伝播を検証して完了する.
    """
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
    """executeだけがcommit後にbatch workerを起こす契約を検証する.

    同じuse caseでdry runとexecuteを順に実行する.
    起床要求が保存後のexecuteにだけ発生することを確認する.

    Returns:
        None: worker起床有無とcommit順序を検証して完了する.
    """
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
