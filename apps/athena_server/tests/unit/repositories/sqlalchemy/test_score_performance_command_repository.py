"""SQLAlchemy score performance command repositoryの永続化契約を検証するtests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

import pytest

from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculationState,
    RecalculationCandidateReason,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    ClaimScorePerformanceCalculation,
    ClaimScorePerformanceRecalculationWork,
    CompleteScorePerformanceCalculation,
    CompleteScorePerformanceRecalculationWork,
    CreateScorePerformanceCalculation,
    CreateScorePerformanceRecalculationBatch,
    CreateScorePerformanceRecalculationWorkItem,
    MarkScorePerformanceRecalculationWorkFailed,
    UpdateScorePerformanceCalculationState,
)
from osu_server.repositories.sqlalchemy.commands.score_performance import (
    SQLAlchemyScorePerformanceCommandRepository,
)
from osu_server.repositories.sqlalchemy.models.score_performance import (
    PerformanceRecalculationBatchModel,
    PerformanceRecalculationWorkItemModel,
    ScorePerformanceCalculationModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.base import Executable

_NOW = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)


class FakeResult:
    """scalar query結果を返すSQLAlchemy result fakeを表す.

    Attributes:
        _value (object | None): scalar_one_or_noneから返す値.
        _values (list[object]): allから返すscalar値の列.
    """

    def __init__(self, value: object | None, values: list[object] | None = None) -> None:
        """queryのscalar結果を指定してresult fakeを初期化する.

        Args:
            value (object | None): 単一scalar結果. 結果がない場合はNone.
            values (list[object] | None): 複数scalar結果. 未指定時は空列.
        """
        self._value: object | None = value
        self._values: list[object] = values or []

    def scalar_one_or_none(self) -> object | None:
        """設定済みの単一scalar結果を返す.

        Returns:
            object | None: queryの単一結果. 結果がない場合はNone.
        """
        return self._value

    def scalars(self) -> FakeResult:
        """複数scalar値を読むためにこのresult fakeを返す.

        Returns:
            FakeResult: allを呼び出せるこのresult fake.
        """
        return self

    def all(self) -> list[object]:
        """設定済みの複数scalar結果を返す.

        Returns:
            list[object]: queryから取得したscalar値の列.
        """
        return self._values


class FakeSession:
    """score performance command mutationを検証するAsyncSession fakeを表す.

    Attributes:
        execute_results (list[object | None]): executeから順に返すscalar値または列.
        get_results (dict[tuple[type[object], object], object]): model型とidentityに対応する
            get結果.
        added (list[object]): addで受け取った永続化model.
        flush_calls (int): flushの呼び出し回数.
        refresh_calls (int): refreshの呼び出し回数.
        commit_calls (int): commitの呼び出し回数.
        rollback_calls (int): rollbackの呼び出し回数.
        _next_performance_id (int): 新規performance calculationへ割り当てる次のID.
        _next_recalculation_batch_id (int): 新規recalculation batchへ割り当てる次のID.
        _next_recalculation_work_item_id (int): 新規recalculation work itemへ割り当てる次のID.
    """

    def __init__(
        self,
        *,
        execute_results: list[object | None] | None = None,
        get_results: dict[tuple[type[object], object], object] | None = None,
    ) -> None:
        """事前resultを指定してcommand mutation用session fakeを初期化する.

        Args:
            execute_results (list[object | None] | None): executeから順に返すresult値.
            get_results (dict[tuple[type[object], object], object] | None): getのmodel型と
                identity別の結果.
        """
        self.execute_results: list[object | None] = execute_results or []
        self.get_results: dict[tuple[type[object], object], object] = get_results or {}
        self.added: list[object] = []
        self.flush_calls: int = 0
        self.refresh_calls: int = 0
        self.commit_calls: int = 0
        self.rollback_calls: int = 0
        self._next_performance_id: int = 100
        self._next_recalculation_batch_id: int = 200
        self._next_recalculation_work_item_id: int = 300

    async def execute(self, statement: Executable) -> FakeResult:
        """SQL commandを消費して設定済みscalar result fakeを返す.

        Args:
            statement (Executable): repositoryが発行するSQL command.

        Returns:
            FakeResult: 次の単一値または複数値を返すresult fake.
        """
        _ = statement
        value = self.execute_results.pop(0) if self.execute_results else None
        if isinstance(value, list):
            return FakeResult(None, cast("list[object]", value))
        return FakeResult(value)

    async def get(self, model_type: type[object], identity: object) -> object | None:
        """model型とidentityに対応する設定済み結果を返す.

        Args:
            model_type (type[object]): 取得対象の永続化model型.
            identity (object): 取得対象のprimary key identity.

        Returns:
            object | None: 設定済みmodel. 結果がない場合はNone.
        """
        return self.get_results.get((model_type, identity))

    def add(self, instance: object) -> None:
        """新規永続化modelをpending add列へ記録する.

        Args:
            instance (object): repositoryが永続化するmodel.

        Returns:
            None: pending modelを記録して呼び出し側へ値を返さずに完了する.
        """
        self.added.append(instance)

    async def flush(self) -> None:
        """未保存modelへIDとtimestampを割り当ててflushを記録する.

        Returns:
            None: pending modelを更新して呼び出し側へ値を返さずに完了する.
        """
        self.flush_calls += 1
        for instance in self.added:
            if (
                isinstance(instance, ScorePerformanceCalculationModel)
                and getattr(instance, "id", None) is None
            ):
                instance.id = self._next_performance_id
                self._next_performance_id += 1
                instance.created_at = _NOW
                instance.updated_at = _NOW
            elif (
                isinstance(instance, PerformanceRecalculationBatchModel)
                and getattr(instance, "id", None) is None
            ):
                instance.id = self._next_recalculation_batch_id
                self._next_recalculation_batch_id += 1
                instance.created_at = _NOW
                instance.updated_at = _NOW
            elif (
                isinstance(instance, PerformanceRecalculationWorkItemModel)
                and getattr(instance, "id", None) is None
            ):
                instance.id = self._next_recalculation_work_item_id
                self._next_recalculation_work_item_id += 1
                instance.created_at = _NOW
                instance.updated_at = _NOW

    async def refresh(self, instance: object) -> None:
        """refresh対象を受け取りrefresh回数を記録する.

        Args:
            instance (object): repositoryがrefreshする永続化model.

        Returns:
            None: refresh回数を増やして呼び出し側へ値を返さずに完了する.
        """
        _ = instance
        self.refresh_calls += 1

    async def commit(self) -> None:
        """commit呼び出しを記録する.

        Returns:
            None: commit回数を増やして呼び出し側へ値を返さずに完了する.
        """
        self.commit_calls += 1

    async def rollback(self) -> None:
        """rollback呼び出しを記録する.

        Returns:
            None: rollback回数を増やして呼び出し側へ値を返さずに完了する.
        """
        self.rollback_calls += 1


async def test_sqlalchemy_repository_creates_current_calculation_without_commit() -> None:
    """現行calculationがない条件でcommitせずqueued calculationを作る契約を検証する.

    Returns:
        None: created resultとflush後のcurrent stateを検証して完了する.
    """
    session = FakeSession(execute_results=[None])
    repo = _repo(session)

    result = await repo.create_or_reuse_calculation(_request(score_id=10))

    assert result.created is True
    assert result.is_replacement is False
    assert result.requires_commit is True
    assert result.calculation.id == 100
    assert result.calculation.is_current is True
    assert result.calculation.state is PerformanceCalculationState.QUEUED
    assert len(session.added) == 1
    assert session.flush_calls == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_request_supersedes_mismatched_pending_replacement() -> None:
    """異なるcalculator versionのpending replacementをsupersedeする契約を検証する.

    Returns:
        None: 新規replacementと旧claimの解除を検証して完了する.
    """
    current = _model(
        calculation_id=1,
        score_id=10,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
    )
    stale_replacement = _model(
        calculation_id=2,
        score_id=10,
        state=PerformanceCalculationState.QUEUED,
        is_current=False,
        calculator_version="4.1.0",
    )
    stale_replacement.claim_owner = "worker-a"
    stale_replacement.claim_expires_at = _NOW + timedelta(minutes=5)
    session = FakeSession(
        execute_results=[current, [stale_replacement]],
        get_results={(ScorePerformanceCalculationModel, 2): stale_replacement},
    )
    repo = _repo(session)

    result = await repo.create_or_reuse_calculation(
        _request(score_id=10, calculator_version="4.2.0")
    )
    stale_finalize = await repo.mark_completed(
        CompleteScorePerformanceCalculation(
            calculation_id=2,
            pp=Decimal("111.111111"),
            star_rating=Decimal("4.32100"),
            calculator_name="rosu-pp-py",
            calculator_version="4.1.0",
            formula_profile=FormulaProfile.VANILLA_RANKED,
            beatmap_file_attachment_id=55,
            beatmap_file_checksum_md5="a" * 32,
            calculated_at=_NOW,
        )
    )

    assert result.created is True
    assert result.is_replacement is True
    assert result.requires_commit is True
    assert result.calculation.id == 100
    assert result.calculation.state is PerformanceCalculationState.QUEUED
    assert result.calculation.is_current is False
    assert stale_replacement.state == PerformanceCalculationState.SUPERSEDED.value
    assert stale_replacement.is_current is False
    assert stale_replacement.claim_owner is None
    assert stale_replacement.claim_expires_at is None
    assert stale_finalize is None
    assert current.state == PerformanceCalculationState.COMPLETED.value
    assert current.is_current is True
    assert len(session.added) == 1
    assert session.flush_calls == 2
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_request_commits_supersede_before_reusing_matching_replacement() -> None:
    """一致するreplacementがある条件で不一致replacementをsupersedeして再利用する契約を検証する.

    Returns:
        None: reused resultとcommit要求を検証して完了する.
    """
    current = _model(
        calculation_id=1,
        score_id=10,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
    )
    matching_replacement = _model(
        calculation_id=2,
        score_id=10,
        state=PerformanceCalculationState.QUEUED,
        is_current=False,
        calculator_version="4.2.0",
    )
    stale_replacement = _model(
        calculation_id=3,
        score_id=10,
        state=PerformanceCalculationState.QUEUED,
        is_current=False,
        calculator_version="4.1.0",
    )
    stale_replacement.claim_owner = "worker-a"
    stale_replacement.claim_expires_at = _NOW + timedelta(minutes=5)
    session = FakeSession(execute_results=[current, [matching_replacement, stale_replacement]])
    repo = _repo(session)

    result = await repo.create_or_reuse_calculation(
        _request(score_id=10, calculator_version="4.2.0")
    )

    assert result.created is False
    assert result.is_replacement is True
    assert result.requires_commit is True
    assert result.calculation.id == matching_replacement.id
    assert result.calculation.state is PerformanceCalculationState.QUEUED
    assert stale_replacement.state == PerformanceCalculationState.SUPERSEDED.value
    assert stale_replacement.is_current is False
    assert stale_replacement.claim_owner is None
    assert stale_replacement.claim_expires_at is None
    assert len(session.added) == 0
    assert session.flush_calls == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_returns_claim_conflict_without_mutation() -> None:
    """別workerがclaim中の条件でclaim conflictをmutationなしで返す契約を検証する.

    Returns:
        None: None resultと既存ownerの保持を検証して完了する.
    """
    model = _model(
        calculation_id=20,
        score_id=10,
        state=PerformanceCalculationState.QUEUED,
        is_current=True,
    )
    model.claim_owner = "worker-a"
    model.claim_expires_at = _NOW + timedelta(minutes=5)
    session = FakeSession(execute_results=[model])
    repo = _repo(session)

    result = await repo.claim_pending_calculation(
        ClaimScorePerformanceCalculation(
            calculation_id=20,
            owner="worker-b",
            claimed_at=_NOW,
            claim_expires_at=_NOW + timedelta(minutes=10),
        )
    )

    assert result is None
    assert model.claim_owner == "worker-a"
    assert session.flush_calls == 0
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_updates_pending_calculation_state() -> None:
    """期待stateが一致するpending calculationを次stateへ更新する契約を検証する.

    Returns:
        None: 更新resultとflushおよびrefreshを検証して完了する.
    """
    model = _model(
        calculation_id=20,
        score_id=10,
        state=PerformanceCalculationState.QUEUED,
        is_current=True,
    )
    session = FakeSession(execute_results=[model])
    repo = _repo(session)

    result = await repo.update_pending_calculation_state(
        UpdateScorePerformanceCalculationState(
            calculation_id=20,
            expected_state=PerformanceCalculationState.QUEUED,
            state=PerformanceCalculationState.FETCHING_FILE,
            transitioned_at=_NOW,
        )
    )

    assert result is not None
    assert result.state is PerformanceCalculationState.FETCHING_FILE
    assert model.state == PerformanceCalculationState.FETCHING_FILE.value
    assert model.updated_at == _NOW
    assert session.flush_calls == 1
    assert session.refresh_calls == 1


async def test_sqlalchemy_repository_does_not_skip_pending_calculation_state() -> None:
    """期待stateを飛ばす遷移条件でpending calculationを更新しない契約を検証する.

    Returns:
        None: None resultと元stateの保持を検証して完了する.
    """
    model = _model(
        calculation_id=20,
        score_id=10,
        state=PerformanceCalculationState.QUEUED,
        is_current=True,
    )
    session = FakeSession(execute_results=[None])
    repo = _repo(session)

    result = await repo.update_pending_calculation_state(
        UpdateScorePerformanceCalculationState(
            calculation_id=20,
            expected_state=PerformanceCalculationState.FETCHING_FILE,
            state=PerformanceCalculationState.CALCULATING,
            transitioned_at=_NOW,
        )
    )

    assert result is None
    assert model.state == PerformanceCalculationState.QUEUED.value
    assert session.flush_calls == 0
    assert session.refresh_calls == 0


async def test_sqlalchemy_repository_does_not_update_terminal_calculation_state() -> None:
    """終端calculationを更新しようとする条件でmutationを行わない契約を検証する.

    Returns:
        None: None resultとterminal stateの保持を検証して完了する.
    """
    model = _model(
        calculation_id=20,
        score_id=10,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
    )
    session = FakeSession(execute_results=[None])
    repo = _repo(session)

    result = await repo.update_pending_calculation_state(
        UpdateScorePerformanceCalculationState(
            calculation_id=20,
            expected_state=PerformanceCalculationState.QUEUED,
            state=PerformanceCalculationState.FETCHING_FILE,
            transitioned_at=_NOW,
        )
    )

    assert result is None
    assert model.state == PerformanceCalculationState.COMPLETED.value
    assert session.flush_calls == 0
    assert session.refresh_calls == 0


async def test_sqlalchemy_replacement_completion_supersedes_old_current_atomically() -> None:
    """claim中のreplacement完了時に旧currentを原子的にsupersedeすることを確認する.

    Returns:
        None: 両計算のclaim解除とcurrent切替が完了したことを示す.

    Raises:
        AssertionError: state, current flag, claim lifecycle, またはflush回数が異なる場合.
    """
    old_current = _model(
        calculation_id=1,
        score_id=10,
        state=PerformanceCalculationState.CALCULATING,
        is_current=True,
    )
    old_current.claim_owner = "old-worker"
    old_current.claim_expires_at = _NOW + timedelta(minutes=5)
    replacement = _model(
        calculation_id=2,
        score_id=10,
        state=PerformanceCalculationState.CALCULATING,
        is_current=False,
        calculator_version="4.1.0",
    )
    replacement.claim_owner = "replacement-worker"
    replacement.claim_expires_at = _NOW + timedelta(minutes=5)
    session = FakeSession(
        execute_results=[old_current],
        get_results={(ScorePerformanceCalculationModel, 2): replacement},
    )
    repo = _repo(session)

    completed = await repo.mark_completed(
        CompleteScorePerformanceCalculation(
            calculation_id=2,
            pp=Decimal("222.222222"),
            star_rating=Decimal("6.54321"),
            calculator_name="rosu-pp-py",
            calculator_version="4.1.0",
            formula_profile=FormulaProfile.VANILLA_RANKED,
            beatmap_file_attachment_id=55,
            beatmap_file_checksum_md5="a" * 32,
            calculated_at=_NOW,
        )
    )

    assert completed is not None
    assert completed.id == 2
    assert completed.is_current is True
    assert completed.state is PerformanceCalculationState.COMPLETED
    assert old_current.is_current is False
    assert old_current.state == PerformanceCalculationState.SUPERSEDED.value
    assert old_current.claim_owner is None
    assert old_current.claim_expires_at is None
    assert replacement.is_current is True
    assert replacement.claim_owner is None
    assert replacement.claim_expires_at is None
    assert replacement.pp == Decimal("222.222222")
    assert session.flush_calls == 2
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_creates_recalculation_batch_without_commit() -> None:
    """再計算work列を指定する条件でcommitせずbatchとwork itemを作る契約を検証する.

    Returns:
        None: batch countと追加modelおよびflush回数を検証して完了する.
    """
    session = FakeSession()
    repo = _repo(session)

    batch = await repo.create_recalculation_batch(
        CreateScorePerformanceRecalculationBatch(
            filters={"all": True},
            reason_counts={
                RecalculationCandidateReason.UNCALCULATED: 1,
                RecalculationCandidateReason.STALE: 1,
            },
            target_calculator_version="4.1.0",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
            work_items=(
                CreateScorePerformanceRecalculationWorkItem(
                    score_id=101,
                    reason=RecalculationCandidateReason.UNCALCULATED,
                ),
                CreateScorePerformanceRecalculationWorkItem(
                    score_id=102,
                    reason=RecalculationCandidateReason.STALE,
                ),
            ),
            created_at=_NOW,
        )
    )

    added_batches = [
        item for item in session.added if isinstance(item, PerformanceRecalculationBatchModel)
    ]
    added_work = [
        item for item in session.added if isinstance(item, PerformanceRecalculationWorkItemModel)
    ]
    assert batch.id == 200
    assert batch.candidate_count == 2
    assert batch.completed_count == 0
    assert batch.unavailable_count == 0
    assert len(added_batches) == 1
    assert len(added_work) == 2
    assert {item.batch_id for item in added_work} == {200}
    assert session.flush_calls == 2
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_claims_recalculation_work_without_commit() -> None:
    """未claimのrecalculation workをclaimする条件でcommitせずownerを記録する契約を検証する.

    Returns:
        None: claimed itemとbatch progressおよびflush回数を検証して完了する.
    """
    batch = _batch_model(batch_id=200, candidate_count=2)
    first = _work_model(work_item_id=300, batch_id=200, score_id=101)
    second = _work_model(work_item_id=301, batch_id=200, score_id=102)
    session = FakeSession(
        execute_results=[[first, second]],
        get_results={(PerformanceRecalculationBatchModel, 200): batch},
    )
    repo = _repo(session)

    claimed = await repo.claim_recalculation_work(
        ClaimScorePerformanceRecalculationWork(
            batch_id=200,
            owner="worker-a",
            claimed_at=_NOW,
            claim_expires_at=_NOW + timedelta(minutes=5),
            limit=2,
        )
    )

    assert [item.id for item in claimed] == [300, 301]
    assert {item.claim_owner for item in claimed} == {"worker-a"}
    assert [item.attempt_count for item in claimed] == [1, 1]
    assert batch.status == "running"
    assert first.state == "claimed"
    assert first.claim_owner == "worker-a"
    assert second.state == "claimed"
    assert session.flush_calls == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_rejects_non_integer_recalculation_reason_count() -> None:
    """永続化済みreason countの非整数値を黙殺しないことを確認する.

    Returns:
        None: 不正なJSONB値がTypeErrorとして観測できたことを示す.

    Raises:
        AssertionError: repositoryが不正値を受理または異なるerrorを返す場合.
    """
    batch = _batch_model(batch_id=200, candidate_count=1)
    batch.reason_counts = {"uncalculated": "1"}
    session = FakeSession(
        execute_results=[None],
        get_results={(PerformanceRecalculationBatchModel, 200): batch},
    )
    repo = _repo(session)

    with pytest.raises(
        TypeError,
        match="batch 200 has non-integer reason_counts value for 'uncalculated': '1'",
    ):
        _ = await repo.get_recalculation_batch_by_id(200)


async def test_sqlalchemy_repository_marks_recalculation_work_completed_without_commit() -> None:
    """claim済みrecalculation workを完了する条件でcommitせずbatchを更新する契約を検証する.

    Returns:
        None: work resultとbatch completion countを検証して完了する.
    """
    batch = _batch_model(batch_id=200, candidate_count=1)
    work = _work_model(work_item_id=300, batch_id=200, score_id=101)
    work.state = "claimed"
    work.claim_owner = "worker-a"
    work.claim_expires_at = _NOW + timedelta(minutes=5)
    work.attempt_count = 1
    session = FakeSession(
        execute_results=[work, batch, [work]],
        get_results={
            (PerformanceRecalculationBatchModel, 200): batch,
        },
    )
    repo = _repo(session)

    completed = await repo.mark_recalculation_work_completed(
        CompleteScorePerformanceRecalculationWork(
            work_item_id=300,
            owner="worker-a",
            calculation_id=500,
            completed_at=_NOW + timedelta(minutes=1),
        )
    )

    assert completed is not None
    assert completed.id == 300
    assert completed.calculation_id == 500
    assert completed.state.value == "completed"
    assert work.claim_owner is None
    assert batch.completed_count == 1
    assert batch.unavailable_count == 0
    assert batch.status == "completed"
    assert session.flush_calls == 2
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_recalculates_batch_progress_from_work_items() -> None:
    """複数work itemがある条件で完了後にbatch progressを再集計する契約を検証する.

    Returns:
        None: completed countとterminal batch statusを検証して完了する.
    """
    batch = _batch_model(batch_id=200, candidate_count=2)
    current = _work_model(work_item_id=300, batch_id=200, score_id=101)
    current.state = "claimed"
    current.claim_owner = "worker-a"
    current.claim_expires_at = _NOW + timedelta(minutes=5)
    current.attempt_count = 1
    prior_completed = _work_model(work_item_id=301, batch_id=200, score_id=102)
    prior_completed.state = "completed"
    prior_completed.calculation_id = 499
    session = FakeSession(
        execute_results=[current, batch, [current, prior_completed]],
    )
    repo = _repo(session)

    completed = await repo.mark_recalculation_work_completed(
        CompleteScorePerformanceRecalculationWork(
            work_item_id=300,
            owner="worker-a",
            calculation_id=500,
            completed_at=_NOW + timedelta(minutes=1),
        )
    )

    assert completed is not None
    assert batch.completed_count == 2
    assert batch.unavailable_count == 0
    assert batch.status == "completed"
    assert session.flush_calls == 2
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_records_failure_without_releasing_claim() -> None:
    """claim済みworkが失敗する条件でclaimを保持してfailureを記録する契約を検証する.

    Returns:
        None: failure messageとclaim stateの保持を検証して完了する.
    """
    batch = _batch_model(batch_id=200, candidate_count=1)
    work = _work_model(work_item_id=300, batch_id=200, score_id=101)
    work.state = "claimed"
    work.claim_owner = "worker-a"
    work.claim_expires_at = _NOW + timedelta(minutes=5)
    work.attempt_count = 1
    session = FakeSession(
        execute_results=[work],
        get_results={(PerformanceRecalculationBatchModel, 200): batch},
    )
    repo = _repo(session)

    failed = await repo.mark_recalculation_work_failed(
        MarkScorePerformanceRecalculationWorkFailed(
            work_item_id=300,
            owner="worker-a",
            error="replacement_calculation_pending",
            failed_at=_NOW + timedelta(minutes=1),
        )
    )

    assert failed is not None
    assert failed.state.value == "claimed"
    assert work.state == "claimed"
    assert work.claim_owner == "worker-a"
    assert work.claim_expires_at == _NOW + timedelta(minutes=5)
    assert work.last_error == "replacement_calculation_pending"
    assert batch.status == "running"
    assert session.flush_calls == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_rejects_stale_work_completion_owner() -> None:
    """古いworkerが完了を報告する条件でwork mutationを拒否する契約を検証する.

    Returns:
        None: None resultとcurrent ownerの保持を検証して完了する.
    """
    work = _work_model(work_item_id=300, batch_id=200, score_id=101)
    work.state = "claimed"
    work.claim_owner = "worker-b"
    work.claim_expires_at = _NOW + timedelta(minutes=10)
    work.attempt_count = 2
    session = FakeSession(
        execute_results=[None],
        get_results={(PerformanceRecalculationWorkItemModel, 300): work},
    )
    repo = _repo(session)

    completed = await repo.mark_recalculation_work_completed(
        CompleteScorePerformanceRecalculationWork(
            work_item_id=300,
            owner="worker-a",
            calculation_id=500,
            completed_at=_NOW + timedelta(minutes=6),
        )
    )

    assert completed is None
    assert work.state == "claimed"
    assert work.claim_owner == "worker-b"
    assert work.calculation_id is None
    assert session.flush_calls == 0
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_sqlalchemy_repository_rejects_stale_work_failure_owner() -> None:
    """古いworkerがfailureを報告する条件でwork mutationを拒否する契約を検証する.

    Returns:
        None: None resultとlast error未変更を検証して完了する.
    """
    work = _work_model(work_item_id=300, batch_id=200, score_id=101)
    work.state = "claimed"
    work.claim_owner = "worker-b"
    work.claim_expires_at = _NOW + timedelta(minutes=10)
    work.attempt_count = 2
    session = FakeSession(
        execute_results=[None],
        get_results={(PerformanceRecalculationWorkItemModel, 300): work},
    )
    repo = _repo(session)

    failed = await repo.mark_recalculation_work_failed(
        MarkScorePerformanceRecalculationWorkFailed(
            work_item_id=300,
            owner="worker-a",
            error="old worker timeout",
            failed_at=_NOW + timedelta(minutes=6),
        )
    )

    assert failed is None
    assert work.state == "claimed"
    assert work.claim_owner == "worker-b"
    assert work.last_error is None
    assert session.flush_calls == 0
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


def _repo(session: FakeSession) -> SQLAlchemyScorePerformanceCommandRepository:
    """指定session fakeを使うscore performance command repositoryを作成する.

    Args:
        session (FakeSession): command mutationを記録するsession fake.

    Returns:
        SQLAlchemyScorePerformanceCommandRepository: test対象のrepository instance.
    """
    return SQLAlchemyScorePerformanceCommandRepository(
        cast("AsyncSession", cast("object", session))
    )


def _request(
    *,
    score_id: int,
    calculator_version: str = "4.0.2",
) -> CreateScorePerformanceCalculation:
    """指定score用のperformance calculation作成requestを作る.

    Args:
        score_id (int): calculation対象scoreの識別子.
        calculator_version (str): 使用するcalculator version.

    Returns:
        CreateScorePerformanceCalculation: queued calculation作成用のrequest.
    """
    return CreateScorePerformanceCalculation(
        score_id=score_id,
        calculator_name="rosu-pp-py",
        calculator_version=calculator_version,
        formula_profile=FormulaProfile.VANILLA_RANKED,
        requested_at=_NOW,
    )


def _model(
    *,
    calculation_id: int,
    score_id: int,
    state: PerformanceCalculationState,
    is_current: bool,
    calculator_version: str = "4.0.2",
) -> ScorePerformanceCalculationModel:
    """指定stateのscore performance calculation modelを作る.

    Args:
        calculation_id (int): calculation modelの識別子.
        score_id (int): calculation対象scoreの識別子.
        state (PerformanceCalculationState): modelに保存するcalculation state.
        is_current (bool): current calculationとして扱うか.
        calculator_version (str): modelに保存するcalculator version.

    Returns:
        ScorePerformanceCalculationModel: stateに整合するtest用のcalculation model.
    """
    model = ScorePerformanceCalculationModel(
        id=calculation_id,
        score_id=score_id,
        state=state.value,
        is_current=is_current,
        pp=Decimal("123.456789") if state is PerformanceCalculationState.COMPLETED else None,
        star_rating=Decimal("5.43210") if state is PerformanceCalculationState.COMPLETED else None,
        calculator_name="rosu-pp-py",
        calculator_version=calculator_version,
        formula_profile=FormulaProfile.VANILLA_RANKED.value,
        beatmap_file_attachment_id=55 if state is PerformanceCalculationState.COMPLETED else None,
        beatmap_file_checksum_md5="a" * 32
        if state is PerformanceCalculationState.COMPLETED
        else None,
        unavailable_reason="osu_file_unusable"
        if state is PerformanceCalculationState.UNAVAILABLE
        else None,
        claim_owner=None,
        claim_expires_at=None,
        attempt_count=0,
        calculated_at=_NOW if state.is_terminal else None,
    )
    model.created_at = _NOW
    model.updated_at = _NOW
    return model


def _batch_model(
    *,
    batch_id: int,
    candidate_count: int,
) -> PerformanceRecalculationBatchModel:
    """指定candidate数のrecalculation batch modelを作る.

    Args:
        batch_id (int): recalculation batchの識別子.
        candidate_count (int): batchが管理するcandidate数.

    Returns:
        PerformanceRecalculationBatchModel: pending stateのtest用batch model.
    """
    model = PerformanceRecalculationBatchModel(
        id=batch_id,
        status="pending",
        filters={"all": True},
        reason_counts={"uncalculated": candidate_count},
        target_calculator_version="4.1.0",
        target_formula_profile=FormulaProfile.VANILLA_RANKED.value,
        candidate_count=candidate_count,
        completed_count=0,
        unavailable_count=0,
    )
    model.created_at = _NOW
    model.updated_at = _NOW
    return model


def _work_model(
    *,
    work_item_id: int,
    batch_id: int,
    score_id: int,
) -> PerformanceRecalculationWorkItemModel:
    """指定score用のpending recalculation work item modelを作る.

    Args:
        work_item_id (int): recalculation work itemの識別子.
        batch_id (int): 所属recalculation batchの識別子.
        score_id (int): recalculation対象scoreの識別子.

    Returns:
        PerformanceRecalculationWorkItemModel: pending stateのtest用work item model.
    """
    model = PerformanceRecalculationWorkItemModel(
        id=work_item_id,
        batch_id=batch_id,
        score_id=score_id,
        reason="uncalculated",
        state="pending",
        calculation_id=None,
        claim_owner=None,
        claim_expires_at=None,
        attempt_count=0,
        last_error=None,
    )
    model.created_at = _NOW
    model.updated_at = _NOW
    return model
