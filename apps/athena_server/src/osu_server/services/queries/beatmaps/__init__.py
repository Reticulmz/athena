"""beatmapのread-only解決query use-caseを公開するpackageを定義する."""

from osu_server.services.queries.beatmaps.direct_search import (
    DirectSearchQuery,
    DirectSearchQueryResult,
)
from osu_server.services.queries.beatmaps.resolve_beatmap import (
    BeatmapResolveQueryResult,
    ResolveBeatmapByChecksumQuery,
    ResolveBeatmapByIdQuery,
)

__all__ = [
    "BeatmapResolveQueryResult",
    "DirectSearchQuery",
    "DirectSearchQueryResult",
    "ResolveBeatmapByChecksumQuery",
    "ResolveBeatmapByIdQuery",
]
