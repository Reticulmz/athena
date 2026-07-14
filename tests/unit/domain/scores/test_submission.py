"""Unit tests for ScoreSubmission domain model."""

from datetime import UTC, datetime

from osu_server.domain.scores import ScoreSubmission, ScoreSubmissionState


def test_submission_creation_with_all_fields() -> None:
    """ScoreSubmission dataclassが全フィールドを受け入れる。"""
    submission = ScoreSubmission(
        id=1,
        fingerprint="abc123def456",
        user_id=100,
        beatmap_checksum="xyz789",
        submitted_at=datetime(2026, 6, 11, 0, 0, 0, tzinfo=UTC),
        state=ScoreSubmissionState.RECEIVED,
        result_snapshot={"score_id": 42, "status": "completed"},
    )

    assert submission.id == 1
    assert submission.fingerprint == "abc123def456"
    assert submission.user_id == 100
    assert submission.state is ScoreSubmissionState.RECEIVED
    assert submission.result_snapshot == {"score_id": 42, "status": "completed"}


def test_submission_without_id() -> None:
    """ID未割り当て(None)のScoreSubmissionを作成できる。"""
    submission = ScoreSubmission(
        id=None,
        fingerprint="test123",
        user_id=100,
        beatmap_checksum="abc",
        submitted_at=datetime.now(UTC),
        state=ScoreSubmissionState.RECEIVED,
        result_snapshot=None,
    )

    assert submission.id is None
    assert submission.result_snapshot is None


def test_submission_state_transitions() -> None:
    """Submissionのstate遷移を検証: received -> processing -> completed."""
    submission = ScoreSubmission(
        id=1,
        fingerprint="fp1",
        user_id=100,
        beatmap_checksum="abc",
        submitted_at=datetime.now(UTC),
        state=ScoreSubmissionState.RECEIVED,
        result_snapshot=None,
    )

    # Initial state
    assert submission.state is ScoreSubmissionState.RECEIVED

    # Transition to processing
    submission = ScoreSubmission(
        id=submission.id,
        fingerprint=submission.fingerprint,
        user_id=submission.user_id,
        beatmap_checksum=submission.beatmap_checksum,
        submitted_at=submission.submitted_at,
        state=ScoreSubmissionState.PROCESSING,
        result_snapshot=None,
    )
    assert submission.state is ScoreSubmissionState.PROCESSING

    # Transition to completed
    submission = ScoreSubmission(
        id=submission.id,
        fingerprint=submission.fingerprint,
        user_id=submission.user_id,
        beatmap_checksum=submission.beatmap_checksum,
        submitted_at=submission.submitted_at,
        state=ScoreSubmissionState.COMPLETED,
        result_snapshot={"score_id": 42},
    )
    assert submission.state is ScoreSubmissionState.COMPLETED
    assert submission.result_snapshot is not None


def test_submission_terminal_rejected_state() -> None:
    """Terminal reject stateを検証。"""
    submission = ScoreSubmission(
        id=1,
        fingerprint="fp2",
        user_id=100,
        beatmap_checksum="abc",
        submitted_at=datetime.now(UTC),
        state=ScoreSubmissionState.TERMINAL_REJECTED,
        result_snapshot={"error": "authorization_failure"},
    )

    assert submission.state is ScoreSubmissionState.TERMINAL_REJECTED
    assert submission.result_snapshot == {"error": "authorization_failure"}
