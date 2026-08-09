"""beatmap metadata 取得と .osu file warmup の command use-case を公開する.

この module は transport や job adapter が利用する beatmap command boundary の型と use-case を
再 export する. 永続化実装や provider の具体型はこの namespace から公開しない.
"""

from osu_server.services.commands.beatmaps.direct_catalog_sync import (
    DirectCatalogScheduleOutcome,
    DirectCatalogScheduler,
    DirectCatalogScheduleResult,
    DirectCatalogWork,
    DirectCatalogWorkKind,
)
from osu_server.services.commands.beatmaps.fetch import (
    BeatmapBlobStorage,
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
)
from osu_server.services.commands.beatmaps.file_warmup import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupOutcome,
    BeatmapFileWarmupRequest,
    BeatmapFileWarmupResolver,
    BeatmapFileWarmupResult,
    RequestBeatmapFileWarmupUseCase,
)

__all__ = [
    "BeatmapBlobStorage",
    "BeatmapFileWarmupEntrance",
    "BeatmapFileWarmupOutcome",
    "BeatmapFileWarmupRequest",
    "BeatmapFileWarmupResolver",
    "BeatmapFileWarmupResult",
    "DirectCatalogScheduleOutcome",
    "DirectCatalogScheduleResult",
    "DirectCatalogScheduler",
    "DirectCatalogWork",
    "DirectCatalogWorkKind",
    "FetchBeatmapFileUseCase",
    "FetchBeatmapMetadataUseCase",
    "RequestBeatmapFileWarmupUseCase",
]
