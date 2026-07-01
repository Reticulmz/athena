"""SQLAlchemy current UserStats command repository tests。"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, cast

from sqlalchemy.dialects import postgresql

from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import (
    UserStatsHitTotals,
    UserStatsProjection,
    UserStatsScope,
)
from osu_server.repositories.sqlalchemy.commands.current_user_stats import (
    SQLAlchemyCurrentUserStatsCommandRepository,
)
from osu_server.repositories.sqlalchemy.models.user_stats import CurrentUserStatsModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ClauseElement


class FakeResult:
    """scalar repository read 用の SQLAlchemy result double。"""

    def __init__(self, value: object | None = None) -> None:
        self._value: object | None = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


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


async def test_replace_upserts_full_scope_and_updates_timestamp() -> None:
    projection = _projection(pp=Decimal("123.45"), accuracy=0.9876)
    model = _model(pp=Decimal("123.45"), accuracy=0.9876)
    session = FakeSession(execute_results=[None, model])
    repo = _repo(session)

    result = await repo.replace(projection)

    assert result == projection
    upsert_sql = _compiled_sql(session.statements[0])
    assert "INSERT INTO current_user_stats" in upsert_sql
    assert "ON CONFLICT (user_id, ruleset, playstyle) DO UPDATE" in upsert_sql
    assert "pp = " in upsert_sql
    assert "accuracy = " in upsert_sql
    assert "play_count = " in upsert_sql
    assert "ranked_score = " in upsert_sql
    assert "total_score = " in upsert_sql
    assert "max_combo = " in upsert_sql
    assert "play_time_seconds = " in upsert_sql
    assert "count_300 = " in upsert_sql
    assert "count_100 = " in upsert_sql
    assert "count_50 = " in upsert_sql
    assert "count_geki = " in upsert_sql
    assert "count_katu = " in upsert_sql
    assert "count_miss = " in upsert_sql
    assert "updated_at = now()" in upsert_sql
    select_sql = _compiled_sql(session.statements[1])
    assert "WHERE current_user_stats.user_id = " in select_sql
    assert "current_user_stats.ruleset = " in select_sql
    assert "current_user_stats.playstyle = " in select_sql
    assert "FOR UPDATE" in select_sql
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


async def test_get_selects_by_full_scope() -> None:
    model = _model(pp=Decimal("10"), accuracy=0.95)
    session = FakeSession(execute_results=[model])
    repo = _repo(session)

    result = await repo.get(_scope())

    assert result == _projection(pp=Decimal("10"), accuracy=0.95)
    sql = _compiled_sql(session.statements[0])
    assert "WHERE current_user_stats.user_id = " in sql
    assert "current_user_stats.ruleset = " in sql
    assert "current_user_stats.playstyle = " in sql
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


def _repo(session: FakeSession) -> SQLAlchemyCurrentUserStatsCommandRepository:
    return SQLAlchemyCurrentUserStatsCommandRepository(
        cast("AsyncSession", cast("object", session))
    )


def _scope() -> UserStatsScope:
    return UserStatsScope(
        user_id=1000,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
    )


def _projection(
    *,
    pp: Decimal,
    accuracy: float,
) -> UserStatsProjection:
    return UserStatsProjection(
        scope=_scope(),
        pp=pp,
        accuracy=accuracy,
        play_count=3,
        ranked_score=1_000_000,
        total_score=2_000_000,
        max_combo=500,
        play_time_seconds=120,
        hit_totals=UserStatsHitTotals(
            count_300=300,
            count_100=10,
            count_50=5,
            count_geki=20,
            count_katu=7,
            count_miss=1,
        ),
    )


def _model(
    *,
    pp: Decimal,
    accuracy: float,
) -> CurrentUserStatsModel:
    return CurrentUserStatsModel(
        user_id=1000,
        ruleset=Ruleset.OSU.value,
        playstyle=Playstyle.VANILLA.value,
        pp=pp,
        accuracy=accuracy,
        play_count=3,
        ranked_score=1_000_000,
        total_score=2_000_000,
        max_combo=500,
        play_time_seconds=120,
        count_300=300,
        count_100=10,
        count_50=5,
        count_geki=20,
        count_katu=7,
        count_miss=1,
    )


def _compiled_sql(statement: ClauseElement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))
