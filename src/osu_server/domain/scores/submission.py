"""ScoreSubmission domain model."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ScoreSubmission:
    """ScoreSubmission domain model for idempotent retry handling."""

    id: int | None
    fingerprint: str
    user_id: int
    beatmap_checksum: str
    submitted_at: datetime
    state: str
    result_snapshot: dict[str, object] | None
