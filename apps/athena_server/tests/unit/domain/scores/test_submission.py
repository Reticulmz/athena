"""ScoreSubmission domain modelの値保持とlifecycle表現を検証する."""

from datetime import UTC, datetime

from osu_server.domain.scores import ScoreSubmission, ScoreSubmissionState


def test_submission_creation_with_all_fields() -> None:
    """ScoreSubmissionが全識別子, state, result snapshotを保持することを検証する.

    Returns:
        None: 構築後の主要fieldを検証して完了する.

    Raises:
        AssertionError: submissionが渡されたmetadataまたはsnapshotを保持しない場合.
    """
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
    """未永続化ScoreSubmissionがNone IDとNone snapshotを保持できることを検証する.

    Returns:
        None: IDとresult snapshotの未割当表現を検証して完了する.

    Raises:
        AssertionError: 未永続化submissionのNone値を保持できない場合.
    """
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
    """submissionをimmutableな状態snapshotで表現できることを検証する.

    RECEIVED, PROCESSING, COMPLETEDの三状態とそれぞれのsnapshotを比較する.

    Returns:
        None: 各状態とCOMPLETEDのresult snapshotを検証して完了する.

    Raises:
        AssertionError: lifecycle stateまたはcompleted snapshotの保持が変わった場合.
    """
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
    """TERMINAL_REJECTED submissionがauthorization failure snapshotを保持できることを検証する.

    Returns:
        None: rejection stateとerror snapshotを検証して完了する.

    Raises:
        AssertionError: terminal rejectionをstateまたはsnapshotで表現できない場合.
    """
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
