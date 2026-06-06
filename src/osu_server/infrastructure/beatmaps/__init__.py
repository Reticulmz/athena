"""Beatmap mirror infrastructure providers, contracts, and errors."""

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
from osu_server.infrastructure.beatmaps.metadata_providers import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.infrastructure.beatmaps.providers import (
    InMemoryBeatmapMetadataProvider,
    MirrorMetadataProvider,
    OsuApiMetadataProvider,
)

__all__ = [
    "BeatmapFileProvider",
    "BeatmapFileSource",
    "BeatmapSourceError",
    "BeatmapSourceErrorCategory",
    "CompositeBeatmapFileProvider",
    "CompositeBeatmapMetadataProvider",
    "InMemoryBeatmapMetadataProvider",
    "MirrorMetadataProvider",
    "OsuApiMetadataProvider",
    "OsuFileFetchResult",
]
