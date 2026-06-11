"""Unit tests for InMemoryScoreRepository."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from osu_server.domain.score.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.memory.score_repository import InMemoryScoreRepository


@pytest.fixture
def repository() -> InMemoryScoreRepository:
    """Create a fresh InMemoryScoreRepository."""
    return InMemoryScoreRepository()


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
        mods=0,
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
        self, repository: InMemoryScoreRepository, sample_score: Score
    ) -> None:
        """Test that create assigns an auto-generated id."""
        created = await repository.create(sample_score)
        assert created.id is not None
        assert created.id == 1

    async def test_create_increments_id(
        self, repository: InMemoryScoreRepository, sample_score: Score
    ) -> None:
        """Test that create increments id for each score."""
        score1 = await repository.create(sample_score)
        score2 = await repository.create(replace(sample_score, online_checksum="online_xyz789"))
        assert score1.id == 1
        assert score2.id == 2

    async def test_create_rejects_duplicate_online_checksum(
        self, repository: InMemoryScoreRepository, sample_score: Score
    ) -> None:
        """Test that create rejects duplicate online_checksum."""
        _ = await repository.create(sample_score)
        with pytest.raises(ValueError, match="online_checksum already exists"):
            _ = await repository.create(sample_score)


class TestExistsByOnlineChecksum:
    """Tests for exists_by_online_checksum() method."""

    async def test_returns_false_when_not_exists(
        self, repository: InMemoryScoreRepository
    ) -> None:
        """Test that exists_by_online_checksum returns False when checksum not found."""
        exists = await repository.exists_by_online_checksum("nonexistent")
        assert exists is False

    async def test_returns_true_when_exists(
        self, repository: InMemoryScoreRepository, sample_score: Score
    ) -> None:
        """Test that exists_by_online_checksum returns True when checksum exists."""
        _ = await repository.create(sample_score)
        exists = await repository.exists_by_online_checksum(sample_score.online_checksum)
        assert exists is True


class TestGetById:
    """Tests for get_by_id() method."""

    async def test_returns_none_when_not_found(self, repository: InMemoryScoreRepository) -> None:
        """Test that get_by_id returns None when id not found."""
        score = await repository.get_by_id(999)
        assert score is None

    async def test_returns_score_when_found(
        self, repository: InMemoryScoreRepository, sample_score: Score
    ) -> None:
        """Test that get_by_id returns score when id found."""
        created = await repository.create(sample_score)
        retrieved = await repository.get_by_id(created.id)  # pyright: ignore[reportArgumentType]
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.online_checksum == created.online_checksum
