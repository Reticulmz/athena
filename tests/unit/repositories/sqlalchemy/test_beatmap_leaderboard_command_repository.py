"""Tests for SQLAlchemy beatmap leaderboard command projection persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy.dialects import postgresql

from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardBeatmapProjectionSlice,
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserProjectionSlice,
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
    """AsyncSession-shaped fake that records statement and transaction usage."""

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


async def test_upsert_targets_projection_unique_index_and_rank_key_guard() -> None:
    model = _model(score_id=12, score=1_100, submitted_at=_NOW + timedelta(seconds=1))
    session = FakeSession(execute_results=[None, model])
    repo = _repo(session)

    result = await repo.upsert_if_better(
        _upsert(score_id=12, score=1_100, submitted_at=_NOW + timedelta(seconds=1))
    )

    assert result.score_id == 12
    assert result.rank_key.score == 1_100
    upsert_sql = _compiled_sql(session.statements[0])
    assert "ON CONFLICT (beatmap_id, ruleset, playstyle, user_id) DO UPDATE" in upsert_sql
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


async def test_get_user_best_uses_scope_without_mod_dimension() -> None:
    model = _model(score_id=10, score=1_000, submitted_at=_NOW)
    session = FakeSession(execute_results=[model])
    repo = _repo(session)

    result = await repo.get_user_best(_scope())

    assert result is not None
    assert result.score_id == 10
    assert "mod_filter_key" not in _compiled_sql(session.statements[0])


async def test_upsert_returns_current_row_when_candidate_does_not_win() -> None:
    existing = _model(score_id=20, score=1_000, submitted_at=_NOW)
    session = FakeSession(execute_results=[None, existing])
    repo = _repo(session)

    result = await repo.upsert_if_better(
        _upsert(score_id=21, score=900, submitted_at=_NOW + timedelta(seconds=1))
    )

    assert result.score_id == 20
    assert result.rank_key == ScoreRankKey(score=1_000, submitted_at=_NOW, score_id=20)
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


async def test_replace_user_projection_slice_deletes_stale_rows_and_reinserts() -> None:
    replacement = _upsert(score_id=30, score=1_200, submitted_at=_NOW)
    persisted = _model(score_id=30, score=1_200, submitted_at=_NOW)
    session = FakeSession(execute_results=[None, None, persisted])
    repo = _repo(session)

    await repo.replace_projection_slice(
        BeatmapLeaderboardUserProjectionSlice(user_id=1000),
        (replacement,),
    )

    delete_sql = _compiled_sql(session.statements[0])
    assert "DELETE FROM beatmap_leaderboard_user_bests" in delete_sql
    assert "WHERE beatmap_leaderboard_user_bests.user_id = " in delete_sql
    assert "INSERT INTO beatmap_leaderboard_user_bests" in _compiled_sql(session.statements[1])
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
) -> BeatmapLeaderboardUserBestScope:
    return BeatmapLeaderboardUserBestScope(
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
        score_id=score_id,
        score=score,
        submitted_at=submitted_at,
    )


def _compiled_sql(statement: ClauseElement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))
