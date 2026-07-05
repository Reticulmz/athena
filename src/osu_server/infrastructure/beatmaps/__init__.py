"""Beatmap external source infrastructure adapters."""

from osu_server.infrastructure.beatmaps.file_sources import BeatmapFileProviderService
from osu_server.infrastructure.beatmaps.metadata_source_adapters import (
    InMemoryBeatmapMetadataProvider,
    MirrorMetadataProviderService,
    OsuApiMetadataProviderService,
)
from osu_server.infrastructure.beatmaps.metadata_sources import (
    CompositeBeatmapMetadataProvider,
)

__all__ = [
    "BeatmapFileProviderService",
    "CompositeBeatmapMetadataProvider",
    "InMemoryBeatmapMetadataProvider",
    "MirrorMetadataProviderService",
    "OsuApiMetadataProviderService",
]
