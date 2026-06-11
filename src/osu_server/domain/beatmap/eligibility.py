"""Beatmap eligibility domain models."""

from dataclasses import dataclass
from enum import IntEnum


class BeatmapStatus(IntEnum):
    """Beatmap submission status."""

    NOT_SUBMITTED = -1
    PENDING = 0
    RANKED = 1
    APPROVED = 2
    QUALIFIED = 3
    LOVED = 4
    WIP = 5
    GRAVEYARD = 6
    UNKNOWN = 7


@dataclass(slots=True, frozen=True)
class EligibilityResult:
    """Result of beatmap eligibility check."""

    eligible: bool
    status: BeatmapStatus
    reason: str | None = None
