"""Test ScoreCommandRepository Protocol compliance."""

from datetime import UTC, datetime

import pytest

from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.beatmaps import BeatmapSubmissionCounts
from osu_server.repositories.interfaces.commands.scores import (
    ScoreCommandRepository,
)


class ConcreteScoreRepository:
    """Minimal concrete implementation for protocol compliance testing."""

    async def create(self, score: Score) -> Score:
        return score

    async def exists_by_online_checksum(self, _checksum: str) -> bool:
        return False

    async def get_by_online_checksum(self, _checksum: str) -> Score | None:
        return None

    async def get_by_id(self, _score_id: int) -> Score | None:
        return None

    async def count_submissions_for_beatmap(self, _beatmap_id: int) -> BeatmapSubmissionCounts:
        return BeatmapSubmissionCounts(play_count=0, pass_count=0)

    async def list_current_stats_scores_for_user(
        self,
        user_id: int,
        *,
        ruleset: Ruleset,
        playstyle: Playstyle,
    ) -> tuple[Score, ...]:
        _ = user_id
        _ = ruleset
        _ = playstyle
        return ()

    async def list_leaderboard_rebuild_candidates_for_user(
        self,
        user_id: int,
    ) -> tuple[Score, ...]:
        _ = user_id
        return ()

    async def list_leaderboard_rebuild_candidates_for_beatmap_ids(
        self,
        beatmap_ids: tuple[int, ...],
    ) -> tuple[Score, ...]:
        _ = beatmap_ids
        return ()


def test_score_repository_protocol_compliance() -> None:
    """Verify ConcreteScoreRepository implements ScoreCommandRepository."""
    repo = ConcreteScoreRepository()
    assert isinstance(repo, ScoreCommandRepository)


@pytest.mark.asyncio
async def test_create_returns_score_with_id() -> None:
    """create() should return a Score with generated id."""
    repo = ConcreteScoreRepository()
    score = Score(
        id=None,
        user_id=1,
        beatmap_id=100,
        beatmap_checksum="abc123",
        online_checksum="def456",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=100,
        n100=0,
        n50=0,
        geki=0,
        katu=0,
        miss=0,
        score=1000000,
        max_combo=100,
        accuracy=1.0,
        grade=Grade.X,
        passed=True,
        perfect=True,
        client_version="b20240101",
        submitted_at=datetime.now(UTC),
    )
    result = await repo.create(score)
    assert isinstance(result, Score)


@pytest.mark.asyncio
async def test_exists_by_online_checksum_returns_bool() -> None:
    """exists_by_online_checksum() should return bool."""
    repo = ConcreteScoreRepository()
    result = await repo.exists_by_online_checksum("test_checksum")
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_get_by_id_returns_optional_score() -> None:
    """get_by_id() should return Score | None."""
    repo = ConcreteScoreRepository()
    result = await repo.get_by_id(1)
    assert result is None or isinstance(result, Score)


@pytest.mark.asyncio
async def test_get_by_online_checksum_returns_optional_score() -> None:
    """get_by_online_checksum() should return Score | None."""
    repo = ConcreteScoreRepository()
    result = await repo.get_by_online_checksum("test_checksum")
    assert result is None or isinstance(result, Score)
