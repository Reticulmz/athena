"""Tests for SQLAlchemy score command repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from sqlalchemy.dialects import postgresql

from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.sqlalchemy.commands.scores import SQLAlchemyScoreCommandRepository
from osu_server.repositories.sqlalchemy.models.score import ScoreModel

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession


class FakeExecuteResult:
    """Minimal SQLAlchemy result substitute for scalar iteration tests."""

    def __init__(self, models: tuple[ScoreModel, ...] = ()) -> None:
        self._models: tuple[ScoreModel, ...] = models

    def scalars(self) -> tuple[ScoreModel, ...]:
        return self._models


class FakeSession:
    """Minimal SQLAlchemy AsyncSession substitute for create() mapping tests."""

    def __init__(self) -> None:
        self.added_model: ScoreModel | None = None
        self.statements: list[object] = []

    def add(self, instance: object) -> None:
        assert isinstance(instance, ScoreModel)
        self.added_model = instance

    async def execute(self, statement: object) -> FakeExecuteResult:
        self.statements.append(statement)
        return FakeExecuteResult()

    async def flush(self) -> None:
        assert self.added_model is not None
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


async def test_empty_beatmap_candidate_selection_does_not_query() -> None:
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.list_leaderboard_rebuild_candidates_for_beatmap_ids(())

    assert result == ()
    assert session.statements == []


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
        beatmap_status_at_submission="pending",
        leaderboard_eligible_at_submission=leaderboard_eligible_at_submission,
    )


def _compiled_select(statement: object) -> str:
    typed_statement = cast("Select[tuple[ScoreModel]]", statement)
    return str(typed_statement.compile(dialect=postgresql.dialect()))
