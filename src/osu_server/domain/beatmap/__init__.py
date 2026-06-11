"""Beatmap domain models."""

from osu_server.domain.beatmap.eligibility import (
    BeatmapStatus,
    EligibilityResult,
)

__all__ = [
    "BeatmapStatus",
    "EligibilityResult",
]
