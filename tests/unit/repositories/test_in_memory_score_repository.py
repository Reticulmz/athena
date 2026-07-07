"""Unit tests for InMemoryScoreCommandRepository."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, PlayTimeSource, Ruleset, Score
from osu_server.repositories.memory.commands.scores import InMemoryScoreCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


@pytest.fixture
def repository() -> InMemoryScoreCommandRepository:
    """Create a fresh InMemoryScoreCommandRepository."""
    return InMemoryScoreCommandRepository(InMemoryCommandRepositoryState())


@pytest.fixture
def sample_score() -> Score:
    """Create a sample score for testing."""
    return Score(
        id=None,
        user_id=1,
        beatmap_id=100,
        beatmap_checksum="abc123",
        online_checksum="online_abc123",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=500,
        n100=50,
        n50=10,
        geki=100,
        katu=20,
        miss=5,
        score=1_000_000,
        max_combo=300,
        accuracy=0.95,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="b20240101",
        submitted_at=datetime.now(UTC),
    )


class TestCreate:
    """Tests for create() method."""

    async def test_create_assigns_id(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """Test that create assigns an auto-generated id."""
        created = await repository.create(sample_score)
        assert created.id is not None
        assert created.id == 1

    async def test_create_increments_id(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """Test that create increments id for each score."""
        score1 = await repository.create(sample_score)
        score2 = await repository.create(replace(sample_score, online_checksum="online_xyz789"))
        assert score1.id == 1
        assert score2.id == 2

    async def test_create_rejects_duplicate_online_checksum(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """Test that create rejects duplicate online_checksum."""
        _ = await repository.create(sample_score)
        with pytest.raises(ValueError, match="online_checksum already exists"):
            _ = await repository.create(sample_score)


class TestExistsByOnlineChecksum:
    """Tests for exists_by_online_checksum() method."""

    async def test_returns_false_when_not_exists(
        self, repository: InMemoryScoreCommandRepository
    ) -> None:
        """Test that exists_by_online_checksum returns False when checksum not found."""
        exists = await repository.exists_by_online_checksum("nonexistent")
        assert exists is False

    async def test_returns_true_when_exists(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """Test that exists_by_online_checksum returns True when checksum exists."""
        _ = await repository.create(sample_score)
        exists = await repository.exists_by_online_checksum(sample_score.online_checksum)
        assert exists is True


class TestGetByOnlineChecksum:
    """Tests for get_by_online_checksum() method."""

    async def test_returns_none_when_not_found(
        self, repository: InMemoryScoreCommandRepository
    ) -> None:
        """Test that get_by_online_checksum returns None when checksum not found."""
        score = await repository.get_by_online_checksum("nonexistent")
        assert score is None

    async def test_returns_score_when_found(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """Test that get_by_online_checksum returns score when checksum exists."""
        created = await repository.create(sample_score)
        retrieved = await repository.get_by_online_checksum(sample_score.online_checksum)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.online_checksum == sample_score.online_checksum


class TestGetById:
    """Tests for get_by_id() method."""

    async def test_returns_none_when_not_found(
        self, repository: InMemoryScoreCommandRepository
    ) -> None:
        """Test that get_by_id returns None when id not found."""
        score = await repository.get_by_id(999)
        assert score is None

    async def test_returns_score_when_found(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """Test that get_by_id returns score when id found."""
        created = await repository.create(sample_score)
        assert created.id is not None
        retrieved = await repository.get_by_id(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.online_checksum == created.online_checksum

    async def test_returns_score_with_timing_fields(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """Test that get_by_id preserves submit timing values."""
        score = replace(
            sample_score,
            fail_time_ms=7_112,
            play_time_seconds=7,
            play_time_source=PlayTimeSource.FAIL_TIME,
            submit_exit_classification="1",
        )

        created = await repository.create(score)
        assert created.id is not None
        retrieved = await repository.get_by_id(created.id)

        assert retrieved is not None
        assert retrieved.fail_time_ms == 7_112
        assert retrieved.play_time_seconds == 7
        assert retrieved.play_time_source is PlayTimeSource.FAIL_TIME
        assert retrieved.submit_exit_classification == "1"


class TestCountSubmissionsForBeatmap:
    """count_submissions_for_beatmap() の tests。"""

    async def test_counts_all_plays_and_passed_scores_for_target_beatmap(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """beatmap の submitted play 数と pass 数を集計する。"""
        _ = await repository.create(sample_score)
        _ = await repository.create(replace(sample_score, online_checksum="failed", passed=False))
        _ = await repository.create(
            replace(sample_score, online_checksum="other-beatmap", beatmap_id=101)
        )

        counts = await repository.count_submissions_for_beatmap(100)

        assert counts.play_count == 2
        assert counts.pass_count == 1

    async def test_returns_zero_counts_for_unknown_beatmap(
        self, repository: InMemoryScoreCommandRepository
    ) -> None:
        """score がない beatmap は 0 件として返す。"""
        counts = await repository.count_submissions_for_beatmap(100)

        assert counts.play_count == 0
        assert counts.pass_count == 0


class TestIncrementReplayViewCount:
    """increment_replay_view_count() の tests。"""

    async def test_increments_existing_score_count(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """対象 score の Replay View Count を 1 増やす。"""
        created = await repository.create(replace(sample_score, replay_view_count=2))
        assert created.id is not None

        incremented = await repository.increment_replay_view_count(created.id)

        updated = await repository.get_by_id(created.id)
        assert incremented is True
        assert updated is not None
        assert updated.replay_view_count == 3
        assert updated.online_checksum == created.online_checksum

    async def test_returns_false_when_score_missing(
        self, repository: InMemoryScoreCommandRepository
    ) -> None:
        """対象 score が存在しない場合は False を返す。"""
        incremented = await repository.increment_replay_view_count(999)

        assert incremented is False


class TestListCurrentStatsScoresForUser:
    """list_current_stats_scores_for_user() の tests。"""

    async def test_filters_user_mode_and_excludes_relax_autopilot(
        self,
        repository: InMemoryScoreCommandRepository,
        sample_score: Score,
    ) -> None:
        """current UserStats 対象の score だけを返す。"""
        included = await repository.create(sample_score)
        _ = await repository.create(replace(sample_score, online_checksum="other-user", user_id=2))
        _ = await repository.create(
            replace(
                sample_score,
                online_checksum="other-ruleset",
                ruleset=Ruleset.MANIA,
            )
        )
        _ = await repository.create(
            replace(
                sample_score,
                online_checksum="relax",
                mods=ModCombination(Mod.RELAX),
            )
        )
        _ = await repository.create(
            replace(
                sample_score,
                online_checksum="autopilot",
                mods=ModCombination(Mod.AUTOPILOT),
            )
        )

        scores = await repository.list_current_stats_scores_for_user(
            1,
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
        )

        assert scores == (included,)
