"""Beatmap infrastructure services."""

from osu_server.infrastructure.beatmap.eligibility_service import (
    BeatmapNotFoundError,
    check_eligibility,
)

__all__ = [
    "BeatmapNotFoundError",
    "check_eligibility",
]
