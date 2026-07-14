"""Tests for SQLAlchemy score command repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ClauseElement

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, PlayTimeSource, Ruleset, Score
from osu_server.repositories.sqlalchemy.commands.scores import SQLAlchemyScoreCommandRepository
from osu_server.repositories.sqlalchemy.models.score import ScoreModel

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession


class FakeExecuteResult:
    """Minimal SQLAlchemy result substitute for scalar iteration tests."""

    def __init__(
        self,
        models: tuple[ScoreModel, ...] = (),
        row: tuple[int, int] = (0, 0),
        value: object | None = None,
    ) -> None:
        self._models: tuple[ScoreModel, ...] = models
        self._row: tuple[int, int] = row
        self._value: object | None = value

    def scalars(self) -> tuple[ScoreModel, ...]:
        return self._models

    def one(self) -> tuple[int, int]:
        return self._row

    def scalar_one_or_none(self) -> object | None:
        return self._value


class FakeSession:
    """Minimal SQLAlchemy AsyncSession substitute for create() mapping tests."""

    def __init__(self) -> None:
        self.added_model: ScoreModel | None = None
        self.statements: list[object] = []
        self.execute_row: tuple[int, int] = (0, 0)
        self.execute_value: object | None = None
        self.flushes: int = 0

    def add(self, instance: object) -> None:
        assert isinstance(instance, ScoreModel)
        self.added_model = instance

    async def execute(self, statement: object) -> FakeExecuteResult:
        self.statements.append(statement)
        return FakeExecuteResult(row=self.execute_row, value=self.execute_value)

    async def flush(self) -> None:
        self.flushes += 1
        if self.added_model is not None:
            self.added_model.id = 42

    async def refresh(self, instance: object) -> None:
        assert instance is self.added_model


async def test_create_persists_leaderboard_eligibility_snapshot() -> None:
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    created = await repository.create(_score(leaderboard_eligible_at_submission=False))

    assert session.added_model is not None
    assert session.added_model.leaderboard_eligible_at_submission is False
    assert created.leaderboard_eligible_at_submission is False


async def test_create_exposes_zero_replay_view_count_for_new_score() -> None:
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    created = await repository.create(_score(leaderboard_eligible_at_submission=False))

    assert session.added_model is not None
    assert session.added_model.replay_view_count == 0
    assert created.replay_view_count == 0


async def test_create_persists_timing_fields() -> None:
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    created = await repository.create(
        replace(
            _score(leaderboard_eligible_at_submission=False),
            fail_time_ms=7_112,
            play_time_seconds=7,
            play_time_source=PlayTimeSource.FAIL_TIME,
            submit_exit_classification="1",
        )
    )

    assert session.added_model is not None
    assert session.added_model.fail_time_ms == 7_112
    assert session.added_model.play_time_seconds == 7
    assert session.added_model.play_time_source == "fail_time"
    assert session.added_model.submit_exit_classification == "1"
    assert created.fail_time_ms == 7_112
    assert created.play_time_seconds == 7
    assert created.play_time_source is PlayTimeSource.FAIL_TIME
    assert created.submit_exit_classification == "1"


async def test_user_rebuild_candidates_select_only_passed_submission_eligible_scores() -> None:
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.list_leaderboard_rebuild_candidates_for_user(1000)

    assert result == ()
    sql = _compiled_select(session.statements[0])
    assert "scores.user_id = %(user_id_1)s" in sql
    assert "scores.passed IS true" in sql
    assert "scores.leaderboard_eligible_at_submission IS true" in sql
    assert "ORDER BY scores.beatmap_id ASC" in sql
    assert "scores.score DESC" in sql
    assert "scores.submitted_at ASC" in sql
    assert "scores.id ASC" in sql


async def test_beatmap_rebuild_candidates_select_target_beatmap_ids() -> None:
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.list_leaderboard_rebuild_candidates_for_beatmap_ids((1, 2))

    assert result == ()
    sql = _compiled_select(session.statements[0])
    assert "scores.beatmap_id IN (__[POSTCOMPILE_beatmap_id_1])" in sql
    assert "scores.passed IS true" in sql
    assert "scores.leaderboard_eligible_at_submission IS true" in sql


async def test_current_stats_scores_select_user_mode_and_exclude_relax_autopilot() -> None:
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.list_current_stats_scores_for_user(
        1000,
        ruleset=Ruleset.MANIA,
        playstyle=Playstyle.VANILLA,
    )

    assert result == ()
    sql = _compiled_select(session.statements[0])
    assert "scores.user_id = %(user_id_1)s" in sql
    assert "scores.ruleset = %(ruleset_1)s" in sql
    assert "scores.playstyle = %(playstyle_1)s" in sql
    assert "& %(mods_1)s" in sql
    assert "ORDER BY scores.submitted_at ASC" in sql


async def test_empty_beatmap_candidate_selection_does_not_query() -> None:
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.list_leaderboard_rebuild_candidates_for_beatmap_ids(())

    assert result == ()
    assert session.statements == []


async def test_count_submissions_for_beatmap_selects_play_and_pass_counts() -> None:
    session = FakeSession()
    session.execute_row = (3, 2)
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.count_submissions_for_beatmap(100)

    assert result.play_count == 3
    assert result.pass_count == 2
    sql = _compiled_select(session.statements[0])
    assert "count(scores.id)" in sql
    assert "CASE WHEN (scores.passed IS true)" in sql
    assert "scores.beatmap_id = %(beatmap_id_1)s" in sql


async def test_increment_replay_view_count_uses_atomic_update_returning() -> None:
    session = FakeSession()
    session.execute_value = 42
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.increment_replay_view_count(42)

    assert result is True
    assert session.flushes == 1
    assert len(session.statements) == 1
    sql = _compiled_clause(session.statements[0])
    assert "UPDATE scores SET" in sql
    assert "replay_view_count=(scores.replay_view_count + " in sql
    assert "WHERE scores.id = " in sql
    assert "RETURNING scores.id" in sql


async def test_increment_replay_view_count_returns_false_when_score_missing() -> None:
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.increment_replay_view_count(404)

    assert result is False
    assert session.flushes == 1


def _score(*, leaderboard_eligible_at_submission: bool) -> Score:
    return Score(
        id=None,
        user_id=1000,
        beatmap_id=1,
        beatmap_checksum="abc123",
        online_checksum="online-checksum",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=100,
        n100=10,
        n50=5,
        geki=0,
        katu=0,
        miss=2,
        score=500000,
        max_combo=99,
        accuracy=0.95,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="20240101",
        submitted_at=datetime.now(UTC),
        beatmap_status_at_submission=BeatmapRankStatus.PENDING,
        leaderboard_eligible_at_submission=leaderboard_eligible_at_submission,
    )


def _compiled_select(statement: object) -> str:
    typed_statement = cast("Select[tuple[ScoreModel]]", statement)
    return str(typed_statement.compile(dialect=postgresql.dialect()))


def _compiled_clause(statement: object) -> str:
    assert isinstance(statement, ClauseElement)
    return str(statement.compile(dialect=postgresql.dialect()))
