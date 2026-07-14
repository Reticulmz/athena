"""Unit tests for InMemoryScoreSubmissionCommandRepository."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.commands.submissions import (
    InMemoryScoreSubmissionCommandRepository,
)


@pytest.fixture
def repository() -> InMemoryScoreSubmissionCommandRepository:
    """Create a fresh in-memory submission repository."""
    return InMemoryScoreSubmissionCommandRepository(InMemoryCommandRepositoryState())


@pytest.fixture
def sample_submission() -> ScoreSubmission:
    """Create a sample submission for testing."""
    return ScoreSubmission(
        id=None,
        fingerprint="abc123",
        user_id=1,
        beatmap_checksum="beatmap_md5",
        submitted_at=datetime.now(tz=UTC),
        state=ScoreSubmissionState.RECEIVED,
        result_snapshot=None,
    )


async def test_create_assigns_id(
    repository: InMemoryScoreSubmissionCommandRepository,
    sample_submission: ScoreSubmission,
) -> None:
    """Test that create() assigns an id to a new submission."""
    created = await repository.create(sample_submission)
    assert created.id is not None
    assert created.id == 1
    assert created.fingerprint == sample_submission.fingerprint


async def test_create_increments_id(
    repository: InMemoryScoreSubmissionCommandRepository,
    sample_submission: ScoreSubmission,
) -> None:
    """Test that create() increments id for subsequent submissions."""
    first = await repository.create(sample_submission)
    second = await repository.create(
        ScoreSubmission(
            id=None,
            fingerprint="def456",
            user_id=2,
            beatmap_checksum="beatmap_md5_2",
            submitted_at=datetime.now(tz=UTC),
            state=ScoreSubmissionState.RECEIVED,
            result_snapshot=None,
        )
    )
    assert first.id == 1
    assert second.id == 2


async def test_create_rejects_duplicate_fingerprint(
    repository: InMemoryScoreSubmissionCommandRepository,
    sample_submission: ScoreSubmission,
) -> None:
    """Test that create() rejects duplicate fingerprint."""
    _ = await repository.create(sample_submission)
    duplicate = ScoreSubmission(
        id=None,
        fingerprint=sample_submission.fingerprint,
        user_id=999,
        beatmap_checksum="different_checksum",
        submitted_at=datetime.now(tz=UTC),
        state=ScoreSubmissionState.RECEIVED,
        result_snapshot=None,
    )
    with pytest.raises(ValueError, match="fingerprint already exists"):
        _ = await repository.create(duplicate)


async def test_get_by_fingerprint_returns_submission(
    repository: InMemoryScoreSubmissionCommandRepository,
    sample_submission: ScoreSubmission,
) -> None:
    """Test that get_by_fingerprint() returns the correct submission."""
    created = await repository.create(sample_submission)
    retrieved = await repository.get_by_fingerprint(sample_submission.fingerprint)
    assert retrieved is not None
    assert retrieved.id == created.id
    assert retrieved.fingerprint == created.fingerprint


async def test_get_by_fingerprint_returns_none_when_not_found(
    repository: InMemoryScoreSubmissionCommandRepository,
) -> None:
    """Test that get_by_fingerprint() returns None when submission not found."""
    retrieved = await repository.get_by_fingerprint("nonexistent")
    assert retrieved is None


async def test_update_state_changes_state(
    repository: InMemoryScoreSubmissionCommandRepository,
    sample_submission: ScoreSubmission,
) -> None:
    """Test that update_state() changes the submission state."""
    created = await repository.create(sample_submission)
    assert created.state is ScoreSubmissionState.RECEIVED
    assert created.id is not None

    await repository.update_state(created.id, ScoreSubmissionState.PROCESSING)
    retrieved = await repository.get_by_fingerprint(sample_submission.fingerprint)
    assert retrieved is not None
    assert retrieved.state is ScoreSubmissionState.PROCESSING


async def test_update_state_raises_when_id_not_found(
    repository: InMemoryScoreSubmissionCommandRepository,
) -> None:
    """Test that update_state() raises ValueError when id not found."""
    with pytest.raises(ValueError, match="Submission not found"):
        await repository.update_state(999, ScoreSubmissionState.PROCESSING)


async def test_idempotent_retrieval(
    repository: InMemoryScoreSubmissionCommandRepository,
    sample_submission: ScoreSubmission,
) -> None:
    """Test idempotent retrieval: same fingerprint returns same submission."""
    first = await repository.create(sample_submission)
    _ = await repository.get_by_fingerprint(sample_submission.fingerprint)
    retrieved_2 = await repository.get_by_fingerprint(sample_submission.fingerprint)

    assert retrieved_2 is not None
    assert retrieved_2.id == first.id
    assert retrieved_2.fingerprint == first.fingerprint
