"""beatmapのread-only解決query use-caseを公開するpackageを定義する."""

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
