"""Beatmap mirror services - resolution, file and metadata providers."""

from osu_server.services.queries.beatmaps.mirror.eligibility_service import (
    BeatmapEligibilityService,
    BeatmapStatusResolver,
)
from osu_server.services.queries.beatmaps.mirror.file_provider_service import (
    BeatmapFileProviderService,
)
from osu_server.services.queries.beatmaps.mirror.metadata_provider_service import (
    InMemoryBeatmapMetadataProvider,
    MirrorMetadataProviderService,
    OsuApiMetadataProviderService,
)
from osu_server.services.queries.beatmaps.mirror.resolution_service import (
    BeatmapMirrorService,
)

__all__ = [
    "BeatmapEligibilityService",
    "BeatmapFileProviderService",
    "BeatmapMirrorService",
    "BeatmapStatusResolver",
    "InMemoryBeatmapMetadataProvider",
    "MirrorMetadataProviderService",
    "OsuApiMetadataProviderService",
]
