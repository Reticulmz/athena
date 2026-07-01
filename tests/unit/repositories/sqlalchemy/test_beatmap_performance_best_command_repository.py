"""SQLAlchemy beatmap performance best projection command repository tests。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy.dialects import postgresql

from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
    BeatmapPerformanceBestBeatmapProjectionSlice,
    BeatmapPerformanceBestScope,
    BeatmapPerformanceBestUserProjectionSlice,
    UpsertBeatmapPerformanceBest,
)
from osu_server.repositories.sqlalchemy.commands.beatmap_performance_bests import (
    SQLAlchemyBeatmapPerformanceBestCommandRepository,
)
from osu_server.repositories.sqlalchemy.models.user_stats import (
    BeatmapPerformanceBestModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ClauseElement

_NOW = datetime(2026, 6, 28, 0, 0, 0, tzinfo=UTC)


class FakeResult:
    """scalar repository read 用の SQLAlchemy result double。"""

    def __init__(self, value: object | None = None) -> None:
        self._value: object | None = value

    def scalar_one_or_none(self) -> object | None:
        return self._value

    def scalars(self) -> tuple[object, ...]:
        if self._value is None:
            return ()
        if isinstance(self._value, tuple):
            return cast("tuple[object, ...]", self._value)
        return (self._value,)


class FakeSession:
    """statement と transaction 使用を記録する AsyncSession 型の fake。"""

    def __init__(self, *, execute_results: list[object | None] | None = None) -> None:
        self.execute_results: list[object | None] = execute_results or []
        self.statements: list[ClauseElement] = []
        self.commit_calls: int = 0
        self.rollback_calls: int = 0

    async def execute(self, statement: ClauseElement) -> FakeResult:
        self.statements.append(statement)
        value = self.execute_results.pop(0) if self.execute_results else None
        return FakeResult(value)

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


async def test_upsert_targets_unique_scope_and_pp_replacement_guard() -> None:
    model = _model(score_id=12, pp=Decimal("101.25"), submitted_at=_NOW)
    session = FakeSession(execute_results=[None, model])
    repo = _repo(session)

    result = await repo.upsert_if_better(
        _upsert(score_id=12, pp=Decimal("101.25"), submitted_at=_NOW)
    )

    assert result.score_id == 12
    assert result.pp == Decimal("101.25")
    upsert_sql = _compiled_sql(session.statements[0])
    assert ("ON CONFLICT (user_id, beatmap_id, ruleset, playstyle) DO UPDATE") in upsert_sql
    assert "performance_calculation_id = " in upsert_sql
    assert "pp = " in upsert_sql
    assert "accuracy = " in upsert_sql
    assert "score = " in upsert_sql
    assert "submitted_at = " in upsert_sql
    assert "updated_at = now()" in upsert_sql
    assert "beatmap_performance_bests.pp < " in upsert_sql
    assert "beatmap_performance_bests.submitted_at > " in upsert_sql
    assert "beatmap_performance_bests.score_id > " in upsert_sql
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_get_best_selects_by_full_scope() -> None:
    model = _model(score_id=10, pp=Decimal("100"), submitted_at=_NOW)
    session = FakeSession(execute_results=[model])
    repo = _repo(session)

    result = await repo.get_best(_scope())

    assert result is not None
    assert result.scope == _scope()
    assert "WHERE beatmap_performance_bests.user_id = " in _compiled_sql(session.statements[0])
    assert "beatmap_performance_bests.beatmap_id = " in _compiled_sql(session.statements[0])


async def test_list_user_bests_selects_user_mode_and_orders_by_pp() -> None:
    model = _model(score_id=10, pp=Decimal("100"), submitted_at=_NOW)
    session = FakeSession(execute_results=[(model,)])
    repo = _repo(session)

    result = await repo.list_user_bests(
        user_id=1000,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
    )

    assert len(result) == 1
    sql = _compiled_sql(session.statements[0])
    assert "WHERE beatmap_performance_bests.user_id = " in sql
    assert "beatmap_performance_bests.ruleset = " in sql
    assert "beatmap_performance_bests.playstyle = " in sql
    assert "beatmap_performance_bests.pp DESC" in sql
    assert "beatmap_performance_bests.submitted_at ASC" in sql


async def test_upsert_returns_current_row_when_candidate_does_not_win() -> None:
    existing = _model(score_id=20, pp=Decimal("100"), submitted_at=_NOW)
    session = FakeSession(execute_results=[None, existing])
    repo = _repo(session)

    result = await repo.upsert_if_better(
        _upsert(
            score_id=21,
            pp=Decimal("99.99"),
            submitted_at=_NOW - timedelta(seconds=1),
        )
    )

    assert result.score_id == 20
    assert result.pp == Decimal("100")
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_replace_user_projection_slice_deletes_stale_rows_and_reinserts() -> None:
    replacement = _upsert(score_id=30, pp=Decimal("120"), submitted_at=_NOW)
    persisted = _model(score_id=30, pp=Decimal("120"), submitted_at=_NOW)
    session = FakeSession(execute_results=[None, None, persisted])
    repo = _repo(session)

    await repo.replace_projection_slice(
        BeatmapPerformanceBestUserProjectionSlice(user_id=1000),
        (replacement,),
    )

    delete_sql = _compiled_sql(session.statements[0])
    assert "DELETE FROM beatmap_performance_bests" in delete_sql
    assert "WHERE beatmap_performance_bests.user_id = " in delete_sql
    assert "INSERT INTO beatmap_performance_bests" in _compiled_sql(session.statements[1])
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_replace_beatmap_projection_slice_deletes_stale_rows_with_empty_rows() -> None:
    session = FakeSession(execute_results=[None])
    repo = _repo(session)

    await repo.replace_projection_slice(
        BeatmapPerformanceBestBeatmapProjectionSlice(beatmap_ids=(1, 2)),
        (),
    )

    delete_sql = _compiled_sql(session.statements[0])
    assert "DELETE FROM beatmap_performance_bests" in delete_sql
    assert "beatmap_performance_bests.beatmap_id IN " in delete_sql
    assert len(session.statements) == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_lock_scope_uses_transaction_advisory_lock() -> None:
    session = FakeSession()
    repo = _repo(session)

    await repo.lock_scope(_scope())

    sql = _compiled_sql(session.statements[0])
    assert "pg_advisory_xact_lock" in sql
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_replace_scope_deletes_exact_scope_and_reinserts_winner() -> None:
    replacement = _upsert(score_id=50, pp=Decimal("130"), submitted_at=_NOW)
    persisted = _model(score_id=50, pp=Decimal("130"), submitted_at=_NOW)
    session = FakeSession(execute_results=[None, None, persisted])
    repo = _repo(session)

    result = await repo.replace_scope(_scope(), replacement)

    assert result is not None
    assert result.score_id == 50
    delete_sql = _compiled_sql(session.statements[0])
    assert "DELETE FROM beatmap_performance_bests" in delete_sql
    assert "WHERE beatmap_performance_bests.user_id = " in delete_sql
    assert "beatmap_performance_bests.beatmap_id = " in delete_sql
    assert "beatmap_performance_bests.ruleset = " in delete_sql
    assert "beatmap_performance_bests.playstyle = " in delete_sql
    assert "INSERT INTO beatmap_performance_bests" in _compiled_sql(session.statements[1])


async def test_replace_scope_can_delete_stale_row_without_replacement() -> None:
    session = FakeSession(execute_results=[None])
    repo = _repo(session)

    result = await repo.replace_scope(_scope(), None)

    assert result is None
    delete_sql = _compiled_sql(session.statements[0])
    assert "DELETE FROM beatmap_performance_bests" in delete_sql
    assert len(session.statements) == 1


async def test_replace_scope_rejects_rows_outside_scope() -> None:
    session = FakeSession()
    repo = _repo(session)

    with pytest.raises(ValueError, match="replacement row is outside projection scope"):
        _ = await repo.replace_scope(
            _scope(),
            _upsert(scope=_scope(user_id=2000), score_id=51, pp=Decimal("130")),
        )

    assert session.statements == []


async def test_replace_projection_slice_rejects_rows_outside_explicit_slice() -> None:
    session = FakeSession()
    repo = _repo(session)

    with pytest.raises(ValueError, match="replacement row is outside projection slice"):
        await repo.replace_projection_slice(
            BeatmapPerformanceBestUserProjectionSlice(user_id=1000),
            (_upsert(scope=_scope(user_id=2000), score_id=40, pp=Decimal("100")),),
        )

    assert session.statements == []


def _repo(session: FakeSession) -> SQLAlchemyBeatmapPerformanceBestCommandRepository:
    return SQLAlchemyBeatmapPerformanceBestCommandRepository(
        cast("AsyncSession", cast("object", session))
    )


def _scope(
    *,
    user_id: int = 1000,
    beatmap_id: int = 1,
) -> BeatmapPerformanceBestScope:
    return BeatmapPerformanceBestScope(
        user_id=user_id,
        beatmap_id=beatmap_id,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
    )


def _upsert(
    *,
    scope: BeatmapPerformanceBestScope | None = None,
    score_id: int,
    pp: Decimal,
    submitted_at: datetime = _NOW,
) -> UpsertBeatmapPerformanceBest:
    return UpsertBeatmapPerformanceBest(
        scope=scope or _scope(),
        score_id=score_id,
        performance_calculation_id=score_id + 10_000,
        pp=pp,
        accuracy=0.98,
        score=1_000_000,
        submitted_at=submitted_at,
    )


def _model(
    *,
    row_id: int = 1,
    user_id: int = 1000,
    beatmap_id: int = 1,
    score_id: int,
    performance_calculation_id: int | None = None,
    pp: Decimal,
    accuracy: float = 0.98,
    score: int = 1_000_000,
    submitted_at: datetime,
) -> BeatmapPerformanceBestModel:
    return BeatmapPerformanceBestModel(
        id=row_id,
        user_id=user_id,
        beatmap_id=beatmap_id,
        ruleset=Ruleset.OSU.value,
        playstyle=Playstyle.VANILLA.value,
        score_id=score_id,
        performance_calculation_id=performance_calculation_id or score_id + 10_000,
        pp=pp,
        accuracy=accuracy,
        score=score,
        submitted_at=submitted_at,
    )


def _compiled_sql(statement: ClauseElement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))
