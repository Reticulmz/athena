"""ビートマップの外部metadataおよびfile source infrastructure adapterを公開する."""

from osu_server.infrastructure.beatmaps.direct_search_upstream import (
    CheeseGullDirectSearchUpstreamProvider,
    NerinyanDirectSearchUpstreamProvider,
    SequentialDirectSearchUpstreamProvider,
)
from osu_server.infrastructure.beatmaps.file_sources import BeatmapFileProviderService
from osu_server.infrastructure.beatmaps.metadata_source_adapters import (
    InMemoryBeatmapMetadataProvider,
    MirrorMetadataProviderService,
    OsuApiBeatmapsetSearchResult,
    OsuApiMetadataProviderService,
)
from osu_server.infrastructure.beatmaps.metadata_sources import (
    CompositeBeatmapMetadataProvider,
)

__all__ = [
    "BeatmapFileProviderService",
    "CheeseGullDirectSearchUpstreamProvider",
    "CompositeBeatmapMetadataProvider",
    "InMemoryBeatmapMetadataProvider",
    "MirrorMetadataProviderService",
    "NerinyanDirectSearchUpstreamProvider",
    "OsuApiBeatmapsetSearchResult",
    "OsuApiMetadataProviderService",
    "SequentialDirectSearchUpstreamProvider",
]
