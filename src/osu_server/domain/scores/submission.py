"""ScoreSubmission domain model."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ScoreSubmissionState(StrEnum):
    """score submission の冪等性記録 lifecycle state"""

    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    TERMINAL_REJECTED = "terminal_rejected"
    RETRYABLE = "retryable"


@dataclass(slots=True)
class ScoreSubmission:
    """score submission の冪等 retry を扱う domain model"""

    id: int | None
    fingerprint: str
    user_id: int
    beatmap_checksum: str
    submitted_at: datetime
    state: ScoreSubmissionState
    result_snapshot: dict[str, object] | None

    def __post_init__(self) -> None:
        self.state = ScoreSubmissionState(self.state)
