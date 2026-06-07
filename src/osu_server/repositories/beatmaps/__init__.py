"""Beatmap mirror repository adapters and source errors."""

from osu_server.repositories.beatmaps.errors import (
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
)
from osu_server.repositories.beatmaps.file_sources import (
    CompositeBeatmapFileProvider,
)
from osu_server.repositories.beatmaps.metadata_providers import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.repositories.beatmaps.providers import (
    InMemoryBeatmapMetadataProvider,
    MirrorMetadataProvider,
    OsuApiMetadataProvider,
)

__all__ = [
    "BeatmapSourceError",
    "BeatmapSourceErrorCategory",
    "CompositeBeatmapFileProvider",
    "CompositeBeatmapMetadataProvider",
    "InMemoryBeatmapMetadataProvider",
    "MirrorMetadataProvider",
    "OsuApiMetadataProvider",
]
