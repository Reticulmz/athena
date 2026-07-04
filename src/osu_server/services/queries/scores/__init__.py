"""Score query use-case package."""

from osu_server.services.queries.scores.beatmap_leaderboards import (
    BeatmapLeaderboardHeader,
    BeatmapLeaderboardOutcomeKind,
    BeatmapLeaderboardQuery,
    BeatmapLeaderboardRequest,
    BeatmapLeaderboardResolveReason,
    BeatmapLeaderboardResult,
    BeatmapPersonalBestRankQuery,
    BeatmapPersonalBestRankQueryInput,
    BeatmapPersonalBestRankQueryResult,
)
from osu_server.services.queries.scores.beatmap_score_listing import BeatmapScoreListingQuery
from osu_server.services.queries.scores.performance import (
    PerformanceResponseQuery,
    PerformanceSubmitResponse,
    PerformanceSubmitResponseQuery,
    PerformanceSubmitResponseState,
)
from osu_server.services.queries.scores.replay_download import (
    ReplayDownloadBodyAssembler,
    ReplayDownloadBodyBuildInput,
    ReplayDownloadBodyBuildResult,
)
from osu_server.services.queries.scores.user_stats import (
    CurrentUserStatsQuery,
    CurrentUserStatsQueryInput,
    CurrentUserStatsQueryResult,
)

__all__ = [
    "BeatmapLeaderboardHeader",
    "BeatmapLeaderboardOutcomeKind",
    "BeatmapLeaderboardQuery",
    "BeatmapLeaderboardRequest",
    "BeatmapLeaderboardResolveReason",
    "BeatmapLeaderboardResult",
    "BeatmapPersonalBestRankQuery",
    "BeatmapPersonalBestRankQueryInput",
    "BeatmapPersonalBestRankQueryResult",
    "BeatmapScoreListingQuery",
    "CurrentUserStatsQuery",
    "CurrentUserStatsQueryInput",
    "CurrentUserStatsQueryResult",
    "PerformanceResponseQuery",
    "PerformanceSubmitResponse",
    "PerformanceSubmitResponseQuery",
    "PerformanceSubmitResponseState",
    "ReplayDownloadBodyAssembler",
    "ReplayDownloadBodyBuildInput",
    "ReplayDownloadBodyBuildResult",
]
