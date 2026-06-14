"""Beatmap query use-case package."""

from osu_server.services.queries.beatmaps.resolve_beatmap import (
    BeatmapResolveQueryResult,
    ResolveBeatmapByChecksumQuery,
    ResolveBeatmapByIdQuery,
)

__all__ = [
    "BeatmapResolveQueryResult",
    "ResolveBeatmapByChecksumQuery",
    "ResolveBeatmapByIdQuery",
]
