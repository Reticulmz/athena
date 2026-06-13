"""Unit tests for InMemoryReplayRepository."""

from __future__ import annotations

import pytest

from osu_server.domain.scores.replay import Replay
from osu_server.repositories.memory.replay_repository import InMemoryReplayRepository


@pytest.fixture
def repository() -> InMemoryReplayRepository:
    """Create a fresh in-memory replay repository."""
    return InMemoryReplayRepository()


@pytest.fixture
def sample_replay() -> Replay:
    """Create a sample replay for testing."""
    return Replay(
        id=None,
        score_id=1,
        blob_id=1,
        checksum_sha256="a" * 64,
        byte_size=12345,
    )


async def test_create_assigns_id(
    repository: InMemoryReplayRepository, sample_replay: Replay
) -> None:
    """Test that create() assigns an id to a new replay."""
    created = await repository.create(sample_replay)
    assert created.id is not None
    assert created.id == 1
    assert created.checksum_sha256 == sample_replay.checksum_sha256


async def test_create_increments_id(
    repository: InMemoryReplayRepository, sample_replay: Replay
) -> None:
    """Test that create() increments id for subsequent replays."""
    first = await repository.create(sample_replay)
    second = await repository.create(
        Replay(
            id=None,
            score_id=2,
            blob_id=2,
            checksum_sha256="b" * 64,
            byte_size=67890,
        )
    )
    assert first.id == 1
    assert second.id == 2


async def test_create_rejects_duplicate_checksum(
    repository: InMemoryReplayRepository, sample_replay: Replay
) -> None:
    """Test that create() rejects duplicate checksum_sha256."""
    _ = await repository.create(sample_replay)
    duplicate = Replay(
        id=None,
        score_id=999,
        blob_id=999,
        checksum_sha256=sample_replay.checksum_sha256,
        byte_size=99999,
    )
    with pytest.raises(ValueError, match="checksum_sha256 already exists"):
        _ = await repository.create(duplicate)


async def test_exists_by_checksum_returns_true_when_exists(
    repository: InMemoryReplayRepository, sample_replay: Replay
) -> None:
    """Test that exists_by_checksum() returns True when replay exists."""
    _ = await repository.create(sample_replay)
    exists = await repository.exists_by_checksum(sample_replay.checksum_sha256)
    assert exists is True


async def test_exists_by_checksum_returns_false_when_not_exists(
    repository: InMemoryReplayRepository,
) -> None:
    """Test that exists_by_checksum() returns False when replay not found."""
    exists = await repository.exists_by_checksum("nonexistent_checksum")
    assert exists is False
