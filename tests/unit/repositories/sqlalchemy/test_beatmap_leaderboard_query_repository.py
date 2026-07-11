"""Tests for SQLAlchemy Beatmap Leaderboard query persistence."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast, override

from sqlalchemy.dialects import postgresql

from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    LeaderboardReadScope,
)
from osu_server.repositories.sqlalchemy.queries.beatmap_leaderboards import (
    SQLAlchemyBeatmapLeaderboardQueryRepository,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from types import TracebackType

    from sqlalchemy.sql.elements import ClauseElement

    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory

_NOW = datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC)
_BEATMAP_ID = 75
_CURRENT_CHECKSUM = "a" * 32


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
    session: FakeQuerySession
    calls: int

    def __init__(self, session: FakeQuerySession) -> None:
        self.session = session
        self.calls = 0

    def __call__(self) -> FakeQuerySession:
        self.calls += 1
        return self.session


async def test_top_rows_rank_user_bests_from_source_scores_and_map_rows() -> None:
    session = FakeQuerySession(
        [FakeResult([_row(score_id=10, user_id=20, score=2_000_000, pp=Decimal("123.456"))])]
    )
    repository = _repository(session)

    rows = await repository.list_top_rows(_scope(), limit=100)

    assert len(rows) == 1
    row = rows[0]
    assert row.score_id == 10
    assert row.user_id == 20
    assert row.username == "User20"
    assert row.ruleset is Ruleset.OSU
    assert row.playstyle is Playstyle.VANILLA
    assert row.score == 2_000_000
    assert row.hit_counts.n300 == 300
    assert row.displayed_mods == ModCombination.none()
    assert row.rank == 1
    assert row.has_replay is True
    assert row.pp == Decimal("123.456")
    assert session.closed is True

    sql = _compiled_sql(session.statements[0])
    assert "FROM scores" in sql
    assert "JOIN scores" in sql
    assert "JOIN beatmaps" in sql
    assert "JOIN users" in sql
    assert "LEFT OUTER JOIN score_performance_calculations" in sql
    assert "LEFT OUTER JOIN" in sql
    assert "role_permissions" in sql
    assert "row_number() OVER" in sql
    assert "PARTITION BY scores.user_id" in sql
    assert "ORDER BY scores.score DESC" in sql
    assert "scores.submitted_at ASC" in sql
    assert "scores.id ASC" in sql
    assert "beatmaps.checksum_md5" in sql
    assert "scores.beatmap_checksum" in sql
    assert "scores.passed IS true" in sql
    assert "scores.leaderboard_eligible_at_submission IS true" in sql
    assert "bit_or(roles.permissions)" in sql
    assert "&" in sql
    assert "EXISTS (SELECT replay_file_attachments.id" in sql
    assert "CASE WHEN" in sql
    assert "score_performance_calculations.pp" in sql


async def test_personal_best_uses_same_filtered_window_ordering_as_top_rows() -> None:
    session = FakeQuerySession(
        [
            FakeResult([_row(score_id=1, user_id=1, score=3_000_000, rank=1)]),
            FakeResult([_row(score_id=52, user_id=52, score=1_000_000, rank=52)]),
        ]
    )
    repository = _repository(session)

    rows = await repository.list_top_rows(_scope(), limit=50)
    personal_best = await repository.get_personal_best(_scope(), viewer_user_id=52)

    assert [row.rank for row in rows] == [1]
    assert personal_best is not None
    assert personal_best.score_id == 52
    assert personal_best.rank == 52
    assert session.closed is True

    top_sql = _compiled_sql(session.statements[0])
    personal_best_sql = _compiled_sql(session.statements[1])
    for sql in (top_sql, personal_best_sql):
        assert "row_number() OVER" in sql
        assert "FROM scores" in sql
        assert "scores.passed IS true" in sql
        assert "scores.leaderboard_eligible_at_submission IS true" in sql
        assert "PARTITION BY scores.user_id" in sql
        assert "ORDER BY scores.score DESC" in sql
        assert "scores.submitted_at ASC" in sql
        assert "scores.id ASC" in sql
    assert "ranked_candidates.rank <= " in top_sql
    assert "ranked_candidates.user_id = " in personal_best_sql


async def test_only_selected_mods_category_applies_mod_filter_key() -> None:
    country_session = FakeQuerySession()
    country_repository = _repository(country_session)
    _ = await country_repository.list_top_rows(
        _scope(
            category=LeaderboardCategory.COUNTRY,
            country="JP",
        ),
        limit=50,
    )

    friends_session = FakeQuerySession()
    friends_repository = _repository(friends_session)
    _ = await friends_repository.list_top_rows(
        _scope(
            category=LeaderboardCategory.FRIENDS,
            eligible_user_ids=(10, 11),
        ),
        limit=50,
    )

    selected_mods_session = FakeQuerySession()
    selected_mods_repository = _repository(selected_mods_session)
    _ = await selected_mods_repository.list_top_rows(
        _scope(
            category=LeaderboardCategory.SELECTED_MODS,
            mod_filter_key=int(Mod.DOUBLE_TIME),
        ),
        limit=50,
    )

    country_sql = _compiled_sql(country_session.statements[0])
    friends_sql = _compiled_sql(friends_session.statements[0])
    selected_mods_sql = _compiled_sql(selected_mods_session.statements[0])
    assert "leaderboard_mod_filter_keys" not in country_sql
    assert "users.country = " in country_sql
    assert "leaderboard_mod_filter_keys" not in friends_sql
    assert "users.id IN " in friends_sql
    assert "scores.leaderboard_mod_filter_keys @> ARRAY[64]" in selected_mods_sql
    assert "users.country = " not in selected_mods_sql


async def test_nullable_pp_does_not_hide_rows_and_pp_sql_is_ranked_approved_only() -> None:
    session = FakeQuerySession(
        [
            FakeResult(
                [
                    _row(score_id=10, user_id=10, score=2_000_000, pp=Decimal("250.125")),
                    _row(score_id=11, user_id=11, score=1_900_000, pp=None, rank=2),
                    _row(score_id=12, user_id=12, score=1_800_000, pp=None, rank=3),
                ]
            )
        ]
    )
    repository = _repository(session)

    rows = await repository.list_top_rows(_scope(), limit=50)

    assert [row.score_id for row in rows] == [10, 11, 12]
    assert [row.pp for row in rows] == [Decimal("250.125"), None, None]
    sql = _compiled_sql(session.statements[0])
    assert "CASE WHEN" in sql
    assert "'ranked'" in sql
    assert "'approved'" in sql
    assert "'loved'" in sql
    assert "'qualified'" in sql


def _repository(
    session: FakeQuerySession,
) -> SQLAlchemyBeatmapLeaderboardQueryRepository:
    factory = FakeSessionFactory(session)
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", factory))
    return SQLAlchemyBeatmapLeaderboardQueryRepository(session_factory)


def _scope(
    *,
    category: LeaderboardCategory = LeaderboardCategory.GLOBAL,
    mod_filter_key: int | None = None,
    country: str | None = None,
    eligible_user_ids: tuple[int, ...] | None = None,
) -> LeaderboardReadScope:
    return LeaderboardReadScope(
        beatmap_id=_BEATMAP_ID,
        beatmap_checksum=_CURRENT_CHECKSUM,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        category=category,
        mod_filter_key=mod_filter_key,
        country=country,
        eligible_user_ids=eligible_user_ids,
    )


def _row(
    *,
    score_id: int,
    user_id: int,
    score: int,
    rank: int = 1,
    pp: Decimal | None = None,
) -> Mapping[str, object]:
    return {
        "score_id": score_id,
        "user_id": user_id,
        "username": f"User{user_id}",
        "beatmap_id": _BEATMAP_ID,
        "ruleset": Ruleset.OSU.value,
        "playstyle": Playstyle.VANILLA.value,
        "score": score,
        "max_combo": 1_234,
        "n50": 1,
        "n100": 10,
        "n300": 300,
        "miss": 0,
        "katu": 5,
        "geki": 50,
        "perfect": True,
        "displayed_mods": ModCombination.none().to_persistence_bitmask(),
        "rank": rank,
        "submitted_at": _NOW,
        "has_replay": True,
        "pp": pp,
    }


def _compiled_sql(statement: ClauseElement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
