"""Beatmap mirror infrastructure -- errors, contracts, and file providers."""

from osu_server.infrastructure.beatmaps.contracts import (
    BeatmapFileProvider,
    BeatmapFileSource,
    OsuFileFetchResult,
)
from osu_server.infrastructure.beatmaps.errors import (
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
)
from osu_server.infrastructure.beatmaps.file_sources import (
    CompositeBeatmapFileProvider,
)

__all__ = [
    "BeatmapFileProvider",
    "BeatmapFileSource",
    "BeatmapSourceError",
    "BeatmapSourceErrorCategory",
    "CompositeBeatmapFileProvider",
    "OsuFileFetchResult",
]
