"""Tests for SQLAlchemy beatmap leaderboard command projection persistence."""

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
    """Small SQLAlchemy result double for scalar repository reads."""

    def __init__(self, value: object | None = None) -> None:
        self._value: object | None = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class FakeSession:
    """Statementとtransaction利用を記録するAsyncSession test double.

    Args:
        execute_results (list[object | None] | None): executeごとに返却または送出する値.

    Attributes:
        execute_results (list[object | None]): executeごとに返却または送出する値.
        statements (list[ClauseElement]): 実行されたSQLAlchemy statement.
        commit_calls (int): session commit呼び出し回数.
        rollback_calls (int): session rollback呼び出し回数.
    """

    def __init__(self, *, execute_results: list[object | None] | None = None) -> None:
        self.execute_results: list[object | None] = execute_results or []
        self.statements: list[ClauseElement] = []
        self.commit_calls: int = 0
        self.rollback_calls: int = 0

    async def execute(self, statement: ClauseElement) -> FakeResult:
        self.statements.append(statement)
        value = self.execute_results.pop(0) if self.execute_results else None
        if isinstance(value, BaseException):
            raise value
        return FakeResult(value)

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


async def test_upsert_targets_projection_unique_index_and_rank_key_guard() -> None:
    """upsertがscore_id lockとprojection rank guardを使用することを確認する.

    Returns:
        None: SQL構造と非commit契約が期待どおりであることを示す.

    Raises:
        AssertionError: lock, 所有確認, またはupsert SQLが契約と異なる場合.
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
    """Global PB read-modify-write用scope lockがtransaction lockであることを確認する.

    Returns:
        None: repositoryがcommitせずPostgreSQL advisory lockを取得したことを示す.

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
    """projection rebuildがsubmit更新と共有するexclusive lockを取得する.

    Returns:
        None: rebuild lockがtransaction終了まで保持されることを示す.

    Raises:
        AssertionError: rebuild lockがsharedまたはrepository commitになる場合.
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
    """別scopeが所有するscore_idをDML前にValueErrorで拒否する.

    Returns:
        None: ownership checkが外側transactionを失敗状態にしないことを示す.

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
    """score_id以外のDB整合性違反を変換せず再送出する.

    Returns:
        None: unrelated IntegrityErrorのidentityが維持されたことを示す.

    Raises:
        AssertionError: unrelated IntegrityErrorがValueErrorへ誤変換された場合.
    """
    error = IntegrityError("INSERT", {}, Exception("unrelated constraint"))
    repo = _repo(FakeSession(execute_results=[None, None, error]))

    with pytest.raises(IntegrityError) as raised:
        _ = await repo.upsert_if_better(_upsert(score_id=12, score=1_000, submitted_at=_NOW))

    assert raised.value is error


async def test_get_user_best_uses_exact_raw_mod_scope() -> None:
    model = _model(score_id=10, score=1_000, submitted_at=_NOW)
    session = FakeSession(execute_results=[model])
    repo = _repo(session)

    result = await repo.get_user_best(_scope())

    assert result is not None
    assert result.score_id == 10
    assert "beatmap_leaderboard_user_bests.mods = " in _compiled_sql(session.statements[0])


async def test_get_global_user_best_ignores_mods_and_orders_all_mod_scopes() -> None:
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
    """rank条件を満たさない候補では現在のprojection rowを返す.

    Returns:
        None: DB側upsert guard後の現在行が返ることを示す.

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
    """user sliceの既存行を削除して新しいprojection rowを再挿入する.

    Returns:
        None: delete後のupsertがscore_id所有確認を含めて実行されたことを示す.

    Raises:
        AssertionError: statement順序またはtransaction所有境界が異なる場合.
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
    session = FakeSession()
    repo = _repo(session)

    with pytest.raises(ValueError, match="replacement row is outside projection slice"):
        await repo.replace_projection_slice(
            BeatmapLeaderboardUserProjectionSlice(user_id=1000),
            (_upsert(scope=_scope(user_id=2000), score_id=40, score=1_000, submitted_at=_NOW),),
        )

    assert session.statements == []


def _repo(session: FakeSession) -> SQLAlchemyBeatmapLeaderboardCommandRepository:
    return SQLAlchemyBeatmapLeaderboardCommandRepository(
        cast("AsyncSession", cast("object", session))
    )


def _scope(
    *,
    user_id: int = 1000,
    beatmap_id: int = 1,
    mods: Mod = Mod.NONE,
) -> BeatmapLeaderboardUserBestScope:
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
    return str(statement.compile(dialect=postgresql.dialect()))
