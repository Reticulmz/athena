"""Tests for SQLAlchemy score command repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.sqlalchemy.commands.scores import SQLAlchemyScoreCommandRepository
from osu_server.repositories.sqlalchemy.models.score import ScoreModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class FakeSession:
    """Minimal SQLAlchemy AsyncSession substitute for create() mapping tests."""

    def __init__(self) -> None:
        self.added_model: ScoreModel | None = None

    def add(self, instance: object) -> None:
        assert isinstance(instance, ScoreModel)
        self.added_model = instance

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
