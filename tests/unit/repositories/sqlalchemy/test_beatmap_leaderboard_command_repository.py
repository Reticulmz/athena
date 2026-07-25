"""SQLAlchemy Beatmap leaderboard command projectionの永続化を検証する."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardBeatmapProjectionSlice,
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserProjectionSlice,
    BeatmapLeaderboardUserScope,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.sqlalchemy.commands.beatmap_leaderboards import (
    SQLAlchemyBeatmapLeaderboardCommandRepository,
)
from osu_server.repositories.sqlalchemy.models.beatmap_leaderboard import (
    BeatmapLeaderboardUserBestModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ClauseElement

_NOW = datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC)


class FakeResult:
    """scalar repository readを再現するSQLAlchemy result test double.

    Attributes:
        _value (object | None): scalar_one_or_noneが返す値.
    """

    def __init__(self, value: object | None = None) -> None:
        """Scalar readの戻り値を持つtest doubleを初期化する.

        Args:
            value (object | None): scalar_one_or_noneから返す値.
        """
        self._value: object | None = value

    def scalar_one_or_none(self) -> object | None:
        """設定済みのscalar read結果を返す.

        Returns:
            object | None: 設定済みの値. 値がない場合はNone.
        """
        return self._value


class FakeSession:
    """statementとtransaction操作を記録するAsyncSession test double.

    Attributes:
        execute_results (list[object | None]): executeごとに返却または送出する値.
        statements (list[ClauseElement]): 実行されたSQLAlchemy statement.
        commit_calls (int): session commit呼び出し回数.
        rollback_calls (int): session rollback呼び出し回数.
    """

    def __init__(self, *, execute_results: list[object | None] | None = None) -> None:
        """Repository callごとの実行結果を受け取るtest sessionを初期化する.

        Args:
            execute_results (list[object | None] | None): executeごとに返却または送出する値.
        """
        self.execute_results: list[object | None] = execute_results or []
        self.statements: list[ClauseElement] = []
        self.commit_calls: int = 0
        self.rollback_calls: int = 0

    async def execute(self, statement: ClauseElement) -> FakeResult:
        """statementを記録し設定済みのread結果または例外を返す.

        Args:
            statement (ClauseElement): repositoryが実行するSQLAlchemy statement.

        Returns:
            FakeResult: 次の設定値を保持するresult test double.

        Raises:
            BaseException: 次の設定値がexception instanceの場合.
        """
        self.statements.append(statement)
        value = self.execute_results.pop(0) if self.execute_results else None
        if isinstance(value, BaseException):
            raise value
        return FakeResult(value)

    async def commit(self) -> None:
        """commit呼び出しを記録してrepositoryのtransaction境界を検証可能にする.

        Returns:
            None: 呼び出し回数を増加して呼び出し側へ値を返さずに完了する.
        """
        self.commit_calls += 1

    async def rollback(self) -> None:
        """rollback呼び出しを記録してrepositoryのtransaction境界を検証可能にする.

        Returns:
            None: 呼び出し回数を増加して呼び出し側へ値を返さずに完了する.
        """
        self.rollback_calls += 1


async def test_upsert_targets_projection_unique_index_and_rank_key_guard() -> None:
    """upsertがscore_id lockとprojection rank guardを使用する契約を検証する.

    Returns:
        None: SQL構造とnon-commit transaction境界を検証して完了する.

    Raises:
        AssertionError: lockとownership checkまたはupsert SQLが契約と異なる場合.
    """
    model = _model(score_id=12, score=1_100, submitted_at=_NOW + timedelta(seconds=1))
    session = FakeSession(execute_results=[None, None, None, model])
    repo = _repo(session)

    result = await repo.upsert_if_better(
        _upsert(score_id=12, score=1_100, submitted_at=_NOW + timedelta(seconds=1))
    )

    assert result.score_id == 12
    assert result.rank_key.score == 1_100
    lock_sql = _compiled_sql(session.statements[0])
    assert "pg_advisory_xact_lock(" in lock_sql
    owner_sql = _compiled_sql(session.statements[1])
    assert "WHERE beatmap_leaderboard_user_bests.score_id = " in owner_sql
    upsert_sql = _compiled_sql(session.statements[2])
    assert "ON CONFLICT (beatmap_id, ruleset, playstyle, user_id, mods) DO UPDATE" in upsert_sql
    assert "ON CONSTRAINT" not in upsert_sql
    assert "score_id = " in upsert_sql
    assert "score = " in upsert_sql
    assert "submitted_at = " in upsert_sql
    assert "updated_at = now()" in upsert_sql
    assert "beatmap_leaderboard_user_bests.beatmap_checksum != " in upsert_sql
    assert "beatmap_leaderboard_user_bests.score < " in upsert_sql
    assert "beatmap_leaderboard_user_bests.submitted_at > " in upsert_sql
    assert "beatmap_leaderboard_user_bests.score_id > " in upsert_sql
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_lock_scope_uses_transaction_advisory_lock() -> None:
    """Global PB read-modify-writeのscope lockがtransaction lockである契約を検証する.

    Returns:
        None: repositoryがcommitせずPostgreSQL advisory lockを取得したことを検証して完了する.

    Raises:
        AssertionError: lock statementまたはtransaction ownershipが異なる場合.
    """
    session = FakeSession()
    repo = _repo(session)

    await repo.lock_scope(_user_scope())

    assert len(session.statements) == 2
    rebuild_guard_sql = _compiled_sql(session.statements[0])
    scope_lock_sql = _compiled_sql(session.statements[1])
    assert "pg_advisory_xact_lock_shared" in rebuild_guard_sql
    assert "pg_advisory_xact_lock(" in scope_lock_sql
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_lock_rebuild_uses_exclusive_transaction_advisory_lock() -> None:
    """Projection rebuildがsubmit更新と共有するexclusive lockを取得する契約を検証する.

    Returns:
        None: rebuild lockがtransaction終了まで保持されることを検証して完了する.

    Raises:
        AssertionError: rebuild lockがshared lockまたはrepository commitになる場合.
    """
    session = FakeSession()
    repo = _repo(session)

    await repo.lock_rebuild()

    assert len(session.statements) == 1
    sql = _compiled_sql(session.statements[0])
    assert "pg_advisory_xact_lock(" in sql
    assert "pg_advisory_xact_lock_shared" not in sql
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_upsert_rejects_score_id_owned_by_another_scope() -> None:
    """別scopeが所有するscore_idをDML前にValueErrorで拒否する契約を検証する.

    Returns:
        None: ownership checkが外側transactionを失敗状態にしないことを検証して完了する.

    Raises:
        AssertionError: 重複score_idでINSERTまたはSAVEPOINTが使用された場合.
    """
    owner = _model(
        mods=Mod.HIDDEN,
        score_id=12,
        score=1_000,
        submitted_at=_NOW,
    )
    session = FakeSession(execute_results=[None, owner])
    repo = _repo(session)

    with pytest.raises(ValueError, match="score_id is already used"):
        _ = await repo.upsert_if_better(_upsert(score_id=12, score=1_000, submitted_at=_NOW))

    assert len(session.statements) == 2
    assert "pg_advisory_xact_lock(" in _compiled_sql(session.statements[0])
    assert "WHERE beatmap_leaderboard_user_bests.score_id = " in _compiled_sql(
        session.statements[1]
    )
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_upsert_preserves_unrelated_integrity_error() -> None:
    """score_id以外のDB整合性違反を変換せず再送出する契約を検証する.

    Returns:
        None: unrelated IntegrityErrorのidentityを検証して完了する.

    Raises:
        AssertionError: unrelated IntegrityErrorがValueErrorへ誤変換された場合.
    """
    error = IntegrityError("INSERT", {}, Exception("unrelated constraint"))
    repo = _repo(FakeSession(execute_results=[None, None, error]))

    with pytest.raises(IntegrityError) as raised:
        _ = await repo.upsert_if_better(_upsert(score_id=12, score=1_000, submitted_at=_NOW))

    assert raised.value is error


async def test_get_user_best_uses_exact_raw_mod_scope() -> None:
    """User best readがraw Modを含む完全一致scopeを使う契約を検証する.

    Returns:
        None: score rowとSQL predicateを検証して完了する.

    Raises:
        AssertionError: read結果またはraw Mod scope predicateが異なる場合.
    """
    model = _model(score_id=10, score=1_000, submitted_at=_NOW)
    session = FakeSession(execute_results=[model])
    repo = _repo(session)

    result = await repo.get_user_best(_scope())

    assert result is not None
    assert result.score_id == 10
    assert "beatmap_leaderboard_user_bests.mods = " in _compiled_sql(session.statements[0])


async def test_get_global_user_best_ignores_mods_and_orders_all_mod_scopes() -> None:
    """Global user best readがModを除外して全raw Mod scopeを順位付けする契約を検証する.

    Returns:
        None: score rowとMod非依存のSQL orderingを検証して完了する.

    Raises:
        AssertionError: read結果またはglobal scope orderingが異なる場合.
    """
    model = _model(score_id=11, score=1_100, submitted_at=_NOW, mods=Mod.HIDDEN)
    session = FakeSession(execute_results=[model])
    repo = _repo(session)

    result = await repo.get_global_user_best(_user_scope())

    assert result is not None
    assert result.score_id == 11
    statement_sql = _compiled_sql(session.statements[0])
    assert "beatmap_leaderboard_user_bests.mods = " not in statement_sql
    assert "ORDER BY beatmap_leaderboard_user_bests.score DESC" in statement_sql


async def test_upsert_returns_current_row_when_candidate_does_not_win() -> None:
    """rank条件を満たさない候補で現在のprojection rowを返す契約を検証する.

    Returns:
        None: DB側upsert guard後の現在行を検証して完了する.

    Raises:
        AssertionError: 劣後候補でprojection rowが置き換わる場合.
    """
    existing = _model(score_id=20, score=1_000, submitted_at=_NOW)
    session = FakeSession(execute_results=[None, None, None, existing])
    repo = _repo(session)

    result = await repo.upsert_if_better(
        _upsert(score_id=21, score=900, submitted_at=_NOW + timedelta(seconds=1))
    )

    assert result.score_id == 20
    assert result.rank_key == ScoreRankKey(score=1_000, submitted_at=_NOW, score_id=20)
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_replace_user_projection_slice_deletes_stale_rows_and_reinserts() -> None:
    """User sliceのstale rowを削除して新しいprojection rowを再挿入する契約を検証する.

    Returns:
        None: delete後のupsertがscore_id ownership checkを含むことを検証して完了する.

    Raises:
        AssertionError: statement順序またはtransaction ownership境界が異なる場合.
    """
    replacement = _upsert(score_id=30, score=1_200, submitted_at=_NOW)
    persisted = _model(score_id=30, score=1_200, submitted_at=_NOW)
    session = FakeSession(execute_results=[None, None, None, None, persisted])
    repo = _repo(session)

    await repo.replace_projection_slice(
        BeatmapLeaderboardUserProjectionSlice(user_id=1000),
        (replacement,),
    )

    delete_sql = _compiled_sql(session.statements[0])
    assert "DELETE FROM beatmap_leaderboard_user_bests" in delete_sql
    assert "WHERE beatmap_leaderboard_user_bests.user_id = " in delete_sql
    assert "pg_advisory_xact_lock(" in _compiled_sql(session.statements[1])
    assert "INSERT INTO beatmap_leaderboard_user_bests" in _compiled_sql(session.statements[3])
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_replace_beatmap_projection_slice_deletes_stale_rows_with_empty_rows() -> None:
    """空のreplacement rowsでbeatmap sliceのstale rowだけを削除する契約を検証する.

    Returns:
        None: delete SQLと追加statementがないことを検証して完了する.

    Raises:
        AssertionError: beatmap slice predicateまたはstatement数が異なる場合.
    """
    session = FakeSession(execute_results=[None])
    repo = _repo(session)

    await repo.replace_projection_slice(
        BeatmapLeaderboardBeatmapProjectionSlice(beatmap_ids=(1, 2)),
        (),
    )

    delete_sql = _compiled_sql(session.statements[0])
    assert "DELETE FROM beatmap_leaderboard_user_bests" in delete_sql
    assert "beatmap_leaderboard_user_bests.beatmap_id IN " in delete_sql
    assert len(session.statements) == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_replace_projection_slice_rejects_rows_outside_explicit_slice() -> None:
    """Explicit projection slice外のreplacement rowをDML前に拒否する契約を検証する.

    Returns:
        None: ValueErrorとstatement未実行を検証して完了する.

    Raises:
        AssertionError: slice外rowが拒否されないかDMLが実行された場合.
    """
    session = FakeSession()
    repo = _repo(session)

    with pytest.raises(ValueError, match="replacement row is outside projection slice"):
        await repo.replace_projection_slice(
            BeatmapLeaderboardUserProjectionSlice(user_id=1000),
            (_upsert(scope=_scope(user_id=2000), score_id=40, score=1_000, submitted_at=_NOW),),
        )

    assert session.statements == []


def _repo(session: FakeSession) -> SQLAlchemyBeatmapLeaderboardCommandRepository:
    """Test sessionをcommand repositoryへ型適合させて構築する.

    Args:
        session (FakeSession): SQL statementとtransaction呼び出しを記録するtest session.

    Returns:
        SQLAlchemyBeatmapLeaderboardCommandRepository: test doubleをsessionとして持つrepository.
    """
    return SQLAlchemyBeatmapLeaderboardCommandRepository(
        cast("AsyncSession", cast("object", session))
    )


def _scope(
    *,
    user_id: int = 1000,
    beatmap_id: int = 1,
    mods: Mod = Mod.NONE,
) -> BeatmapLeaderboardUserBestScope:
    """Raw Modを含むuser best scopeをtest用の既定値で構築する.

    Args:
        user_id (int): scopeに含めるuser ID.
        beatmap_id (int): scopeに含めるbeatmap ID.
        mods (Mod): persistence bitmaskへ変換するraw Mod値.

    Returns:
        BeatmapLeaderboardUserBestScope: 指定したuserとbeatmapとModの完全一致scope.
    """
    return BeatmapLeaderboardUserBestScope(
        beatmap_id=beatmap_id,
        beatmap_checksum=f"{beatmap_id:032x}",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        user_id=user_id,
        mods=ModCombination(mods),
    )


def _user_scope(
    *,
    user_id: int = 1000,
    beatmap_id: int = 1,
) -> BeatmapLeaderboardUserScope:
    """Modを除外するuser scopeをtest用の既定値で構築する.

    Args:
        user_id (int): scopeに含めるuser ID.
        beatmap_id (int): scopeに含めるbeatmap ID.

    Returns:
        BeatmapLeaderboardUserScope: 指定したuserとbeatmapのglobal best scope.
    """
    return BeatmapLeaderboardUserScope(
        beatmap_id=beatmap_id,
        beatmap_checksum=f"{beatmap_id:032x}",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        user_id=user_id,
    )


def _upsert(
    *,
    scope: BeatmapLeaderboardUserBestScope | None = None,
    score_id: int,
    score: int,
    submitted_at: datetime,
) -> UpsertBeatmapLeaderboardUserBest:
    """Leaderboard projectionのupsert commandをtest入力から構築する.

    Args:
        scope (BeatmapLeaderboardUserBestScope | None): 使用する完全一致scope. Noneなら既定scope.
        score_id (int): projectionへ関連付けるscore ID.
        score (int): rank keyに使うscore値.
        submitted_at (datetime): scoreの送信時刻.

    Returns:
        UpsertBeatmapLeaderboardUserBest: rank keyを含むupsert command.
    """
    return UpsertBeatmapLeaderboardUserBest(
        scope=scope or _scope(),
        score_id=score_id,
        rank_key=ScoreRankKey(score=score, submitted_at=submitted_at, score_id=score_id),
    )


def _model(
    *,
    row_id: int = 1,
    beatmap_id: int = 1,
    user_id: int = 1000,
    mods: Mod = Mod.NONE,
    score_id: int,
    score: int,
    submitted_at: datetime,
) -> BeatmapLeaderboardUserBestModel:
    """SQLAlchemy leaderboard projection modelをtest用の値で構築する.

    Args:
        row_id (int): persistence modelのprimary key.
        beatmap_id (int): projectionが参照するbeatmap ID.
        user_id (int): projectionが参照するuser ID.
        mods (Mod): persistence bitmaskへ変換するraw Mod値.
        score_id (int): projectionが参照するscore ID.
        score (int): rank keyに使うscore値.
        submitted_at (datetime): scoreの送信時刻.

    Returns:
        BeatmapLeaderboardUserBestModel: repository readがdomain valueへ変換するmodel.
    """
    return BeatmapLeaderboardUserBestModel(
        id=row_id,
        beatmap_id=beatmap_id,
        beatmap_checksum=f"{beatmap_id:032x}",
        ruleset=Ruleset.OSU.value,
        playstyle=Playstyle.VANILLA.value,
        user_id=user_id,
        mods=int(mods),
        score_id=score_id,
        score=score,
        submitted_at=submitted_at,
    )


def _compiled_sql(statement: ClauseElement) -> str:
    """SQLAlchemy statementをPostgreSQL literal SQLへコンパイルする.

    Args:
        statement (ClauseElement): SQL構造を検証する対象statement.

    Returns:
        str: PostgreSQL dialectでコンパイルしたSQL文字列.
    """
    return str(statement.compile(dialect=postgresql.dialect()))
