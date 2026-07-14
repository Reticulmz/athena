"""ScoreSubmission domain model."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ScoreSubmissionState(StrEnum):
    """score submission の冪等性記録 lifecycle state.

    Attributes:
        RECEIVED (ScoreSubmissionState): requestを受理した直後.
        PROCESSING (ScoreSubmissionState): durable workflowを処理中.
        COMPLETED (ScoreSubmissionState): score submitが完了した状態.
        TERMINAL_REJECTED (ScoreSubmissionState): 結果が変わらない拒否状態.
        RETRYABLE (ScoreSubmissionState): 一時的な失敗により再処理できる状態.
    """

    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    TERMINAL_REJECTED = "terminal_rejected"
    RETRYABLE = "retryable"


@dataclass(slots=True)
class ScoreSubmission:
    """score submission の冪等 retry を扱う domain model.

    Attributes:
        id (int | None): 永続化前はNoneとなるsubmission ID.
        fingerprint (str): 冪等性判定に使用するrequest fingerprint.
        user_id (int): submissionを送信したUser ID.
        beatmap_checksum (str): submission対象Beatmapのchecksum.
        submitted_at (datetime): clientがscoreを送信した日時.
        state (ScoreSubmissionState): submissionのlifecycle state.
        result_snapshot (dict[str, object] | None): retry response用snapshot.
    """

    id: int | None
    fingerprint: str
    user_id: int
    beatmap_checksum: str
    submitted_at: datetime
    state: ScoreSubmissionState
    result_snapshot: dict[str, object] | None

    def __post_init__(self) -> None:
        self.state = ScoreSubmissionState(self.state)
