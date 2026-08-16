"""Beatmap domain modelの互換re-exportを提供するmodule."""

from osu_server.domain.beatmaps.entities import (
    Beatmap,
    BeatmapFileAttachment,
    BeatmapSet,
)
from osu_server.domain.beatmaps.fetch_targets import (
    BeatmapFetchQueuePayload,
    BeatmapFetchRecord,
    BeatmapFetchTarget,
    BeatmapFetchTargetKind,
    BeatmapMetadataLookupKind,
    BeatmapMetadataLookupTarget,
)
from osu_server.domain.beatmaps.freshness import (
    BeatmapFreshnessDecision,
    BeatmapFreshnessPolicy,
)
from osu_server.domain.beatmaps.providers import (
    BeatmapFileProvider,
    BeatmapMetadataProvider,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    OsuFileFetchResult,
)
from osu_server.domain.beatmaps.resolution import (
    BeatmapEligibility,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSetResolveResult,
)
from osu_server.domain.beatmaps.states import (
    BeatmapFetchState,
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
    map_external_status,
)

__all__ = [
    "Beatmap",
    "BeatmapEligibility",
    "BeatmapFetchQueuePayload",
    "BeatmapFetchRecord",
    "BeatmapFetchState",
    "BeatmapFetchTarget",
    "BeatmapFetchTargetKind",
    "BeatmapFileAttachment",
    "BeatmapFileProvider",
    "BeatmapFileSource",
    "BeatmapFileState",
    "BeatmapFreshnessDecision",
    "BeatmapFreshnessPolicy",
    "BeatmapMetadataLookupKind",
    "BeatmapMetadataLookupTarget",
    "BeatmapMetadataProvider",
    "BeatmapMetadataSource",
    "BeatmapMode",
    "BeatmapRankStatus",
    "BeatmapResolveOptions",
    "BeatmapResolveResult",
    "BeatmapSet",
    "BeatmapSetResolveResult",
    "BeatmapSnapshot",
    "BeatmapSourceVerification",
    "BeatmapsetSnapshot",
    "LocalBeatmapStatus",
    "OsuFileFetchResult",
    "map_external_status",
]
