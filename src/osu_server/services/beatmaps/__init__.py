"""Beatmap service-layer providers."""

from osu_server.services.beatmaps.metadata_providers import CompositeBeatmapMetadataProvider
from osu_server.services.beatmaps.providers import (
    InMemoryBeatmapMetadataProvider,
    MirrorMetadataProvider,
    OsuApiMetadataProvider,
)

__all__ = [
    "CompositeBeatmapMetadataProvider",
    "InMemoryBeatmapMetadataProvider",
    "MirrorMetadataProvider",
    "OsuApiMetadataProvider",
]
