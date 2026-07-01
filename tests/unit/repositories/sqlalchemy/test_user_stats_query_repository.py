"""Tests for SQLAlchemy current UserStats query persistence。"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from typing import TYPE_CHECKING, cast, override

from sqlalchemy.dialects import postgresql

from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import UserPerformanceBest
from osu_server.repositories.sqlalchemy.queries.user_stats import (
    SQLAlchemyUserStatsQueryRepository,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from types import TracebackType

    from sqlalchemy.sql.elements import ClauseElement

    from osu_server.repositories.interfaces.queries.user_stats import (
        UserStatsQueryRepository,
        UserStatsSourceRead,
    )
    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory


class FakeResult:
    """Small SQLAlchemy result double returning mapping rows."""

    _rows: list[Mapping[str, object]]

    def __init__(self, rows: Iterable[Mapping[str, object]] = ()) -> None:
        self._rows = list(rows)

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[Mapping[str, object]]:
        return self._rows


class FakeQuerySession(AbstractAsyncContextManager["FakeQuerySession"]):
    """AsyncSession-shaped fake that fails on mutation APIs."""

    closed: bool
    statements: list[ClauseElement]
    _execute_results: list[FakeResult]

    def __init__(self, execute_results: Iterable[FakeResult] = ()) -> None:
        self.closed = False
        self.statements = []
        self._execute_results = list(execute_results)

    @override
    async def __aenter__(self) -> FakeQuerySession:
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type
        _ = exc
        _ = traceback
        await self.close()

    async def execute(self, statement: ClauseElement) -> FakeResult:
        self.statements.append(statement)
        if self._execute_results:
            return self._execute_results.pop(0)
        return FakeResult()

    def add(self, instance: object) -> None:
        _ = instance
        raise AssertionError("query repository must not add instances")

    async def delete(self, instance: object) -> None:
        _ = instance
        raise AssertionError("query repository must not delete instances")

    async def merge(self, instance: object) -> object:
        _ = instance
        raise AssertionError("query repository must not merge instances")

    async def flush(self) -> None:
        raise AssertionError("query repository must not flush")

    async def commit(self) -> None:
        raise AssertionError("query repository must not commit")

    async def rollback(self) -> None:
        raise AssertionError("query repository must not rollback")

    async def refresh(self, instance: object) -> None:
        _ = instance
        raise AssertionError("query repository must not refresh")

    async def close(self) -> None:
        self.closed = True


class FakeSessionFactory:
    """Query session factory double."""

    session: FakeQuerySession
    calls: int

    def __init__(self, session: FakeQuerySession) -> None:
        self.session = session
        self.calls = 0

    def __call__(self) -> FakeQuerySession:
        self.calls += 1
        return self.session


async def test_reads_current_stats_sources_with_batched_sql_and_row_mapping() -> None:
    session = FakeQuerySession(
        [
            FakeResult([{"user_id": 10}, {"user_id": 20}]),
            FakeResult(
                [
                    {
                        "user_id": 20,
                        "pp": Decimal("200"),
                        "accuracy": 0.98,
                        "play_count": 5,
                        "ranked_score": 500,
                        "total_score": 700,
                        "max_combo": 999,
                        "play_time_seconds": 90,
                        "count_300": 100,
                        "count_100": 5,
                        "count_50": 1,
                        "count_geki": 0,
                        "count_katu": 0,
                        "count_miss": 2,
                    }
                ]
            ),
            FakeResult(
                [
                    {
                        "user_id": 10,
                        "play_count": 2,
                        "ranked_score": 100,
                        "total_score": 300,
                        "max_combo": 777,
                        "play_time_seconds": 45,
                        "count_300": 40,
                        "count_100": 4,
                        "count_50": 2,
                        "count_geki": 0,
                        "count_katu": 0,
                        "count_miss": 1,
                    }
                ]
            ),
            FakeResult(
                [
                    {"user_id": 10, "pp": Decimal("120"), "accuracy": 0.99},
                    {"user_id": 10, "pp": Decimal("80"), "accuracy": 0.95},
                ]
            ),
            FakeResult([{"user_id": 20, "global_rank": 5}]),
        ]
    )
    repository: UserStatsQueryRepository = _repository(session)

    result = await repository.read_current_stats_sources(
        (10, 999, 20, 10),
        ruleset=Ruleset.MANIA,
        playstyle=Playstyle.VANILLA,
    )

    _assert_source_read(result)
    assert session.closed is True
    _assert_batched_sql(session)


def _assert_source_read(result: UserStatsSourceRead) -> None:
    assert [source.user_id for source in result.users] == [10, 20]
    assert result.users[0].play_count == 2
    assert result.users[0].ranked_score == 100
    assert result.users[0].total_score == 300
    assert result.users[0].max_combo == 777
    assert result.users[0].play_time_seconds == 45
    assert result.users[0].best_performances == (
        UserPerformanceBest(pp=Decimal("120"), accuracy=0.99),
        UserPerformanceBest(pp=Decimal("80"), accuracy=0.95),
    )
    assert result.users[0].hit_totals.count_300 == 40
    assert result.users[1].play_count == 5
    assert result.users[1].pp == Decimal("200")
    assert result.users[1].accuracy == 0.98
    assert result.users[1].global_rank == 5
    assert result.users[1].hit_totals.count_300 == 100
    assert result.users[1].best_performances == ()
    assert result.rank_inputs == ()


def _assert_batched_sql(session: FakeQuerySession) -> None:
    assert len(session.statements) == 5
    known_sql = _compiled_sql(session.statements[0])
    requested_projection_sql = _compiled_sql(session.statements[1])
    aggregate_sql = _compiled_sql(session.statements[2])
    requested_bests_sql = _compiled_sql(session.statements[3])
    requested_rank_sql = _compiled_sql(session.statements[4])

    assert "FROM users" in known_sql
    assert "users.id IN" in known_sql
    assert "FROM current_user_stats" in requested_projection_sql
    assert "current_user_stats.user_id IN" in requested_projection_sql
    assert "current_user_stats.ruleset = 3" in requested_projection_sql
    assert "current_user_stats.playstyle = 0" in requested_projection_sql
    assert "FROM scores" in aggregate_sql
    assert "count(scores.id)" in aggregate_sql
    assert "sum(scores.score)" in aggregate_sql
    assert "sum(scores.n300)" in aggregate_sql
    assert "sum(scores.geki)" in aggregate_sql
    assert "passed IS true" in aggregate_sql
    assert "leaderboard_eligible_at_submission IS true" in aggregate_sql
    assert "scores.ruleset = 3" in aggregate_sql
    assert "scores.playstyle = 0" in aggregate_sql
    assert "ranked_score_candidates" in aggregate_sql
    assert "max(" in aggregate_sql
    assert "& 8320" in aggregate_sql
    assert "GROUP BY scores.user_id" in aggregate_sql
    assert "IN (10)" in aggregate_sql
    assert "FROM beatmap_performance_bests" in requested_bests_sql
    assert "beatmap_performance_bests.user_id IN" in requested_bests_sql
    assert "IN (10)" in requested_bests_sql
    assert "beatmap_performance_bests.ruleset = 3" in requested_bests_sql
    assert "beatmap_performance_bests.playstyle = 0" in requested_bests_sql
    assert "beatmap_performance_bests.pp DESC" in requested_bests_sql
    assert "beatmap_performance_bests.submitted_at ASC" in requested_bests_sql
    assert "beatmap_performance_bests.score_id ASC" in requested_bests_sql
    assert "FROM current_user_stats" in requested_rank_sql
    assert "JOIN users" in requested_rank_sql
    assert "target_role_permissions" in requested_rank_sql
    assert "better_role_permissions" in requested_rank_sql
    assert "current_user_stats_1.user_id IN" in requested_rank_sql
    assert "current_user_stats_1.ruleset = 3" in requested_rank_sql
    assert "current_user_stats_1.playstyle = 0" in requested_rank_sql
    assert "count(CASE WHEN" in requested_rank_sql
    assert "current_user_stats_2.pp > current_user_stats_1.pp" in requested_rank_sql
    assert "current_user_stats_2.user_id < current_user_stats_1.user_id" in (requested_rank_sql)
    assert "&" in requested_rank_sql


async def test_projected_users_skip_fallback_aggregate_and_best_reads() -> None:
    session = FakeQuerySession(
        [
            FakeResult([{"user_id": 10}, {"user_id": 20}]),
            FakeResult(
                [
                    _projection_row(user_id=10, pp=Decimal("300")),
                    _projection_row(user_id=20, pp=Decimal("200")),
                ]
            ),
            FakeResult(
                [
                    {"user_id": 10, "global_rank": 1},
                    {"user_id": 20, "global_rank": 2},
                ]
            ),
        ]
    )
    repository = _repository(session)

    result = await repository.read_current_stats_sources(
        (10, 20),
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
    )

    assert [source.user_id for source in result.users] == [10, 20]
    assert [source.global_rank for source in result.users] == [1, 2]
    assert len(session.statements) == 3
    assert "FROM users" in _compiled_sql(session.statements[0])
    assert "FROM current_user_stats" in _compiled_sql(session.statements[1])
    assert "FROM current_user_stats" in _compiled_sql(session.statements[2])


async def test_empty_request_returns_empty_read_without_opening_session() -> None:
    session = FakeQuerySession()
    repository = _repository(session)

    result = await repository.read_current_stats_sources(())

    assert result.users == ()
    assert result.rank_inputs == ()
    assert session.closed is False
    assert session.statements == []


async def test_unknown_only_request_closes_session_after_known_user_read() -> None:
    session = FakeQuerySession([FakeResult()])
    repository = _repository(session)

    result = await repository.read_current_stats_sources((404,))

    assert result.users == ()
    assert result.rank_inputs == ()
    assert session.closed is True
    assert len(session.statements) == 1


def _repository(session: FakeQuerySession) -> SQLAlchemyUserStatsQueryRepository:
    factory = FakeSessionFactory(session)
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", factory))
    return SQLAlchemyUserStatsQueryRepository(session_factory)


def _projection_row(
    *,
    user_id: int,
    pp: Decimal,
) -> Mapping[str, object]:
    return {
        "user_id": user_id,
        "pp": pp,
        "accuracy": 0.98,
        "play_count": 5,
        "ranked_score": 500,
        "total_score": 700,
        "max_combo": 999,
        "play_time_seconds": 90,
        "count_300": 100,
        "count_100": 5,
        "count_50": 1,
        "count_geki": 0,
        "count_katu": 0,
        "count_miss": 2,
    }


def _compiled_sql(statement: ClauseElement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
