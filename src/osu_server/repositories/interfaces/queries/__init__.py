"""Query repository interface package."""

from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    BeatmapLeaderboardQueryRepository,
    BeatmapLeaderboardRow,
    LeaderboardReadScope,
    ScoreHitCounts,
)
from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
    BeatmapScoreListingQueryRepository,
)
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.queries.blobs import BlobQueryRepository
from osu_server.repositories.interfaces.queries.channels import ChannelQueryRepository
from osu_server.repositories.interfaces.queries.chat import (
    ChatHistoryMessage,
    ChatHistoryQueryRepository,
)
from osu_server.repositories.interfaces.queries.friends import (
    FriendRelationshipQueryRepository,
)
from osu_server.repositories.interfaces.queries.personal_bests import (
    PersonalBestQueryRepository,
)
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.score_performance import (
    RecalculationCandidateReason,
    ScorePerformanceCandidateSelection,
    ScorePerformanceQueryRepository,
    ScorePerformanceRecalculationCandidate,
    ScorePerformanceRecalculationCandidateResult,
)
from osu_server.repositories.interfaces.queries.scores import ScoreQueryRepository
from osu_server.repositories.interfaces.queries.user_stats import (
    UserStatsQueryRepository,
    UserStatsRankInput,
    UserStatsSourceRead,
    UserStatsSourceRow,
)
from osu_server.repositories.interfaces.queries.users import UserQueryRepository

__all__ = [
    "BeatmapLeaderboardQueryRepository",
    "BeatmapLeaderboardRow",
    "BeatmapQueryRepository",
    "BeatmapScoreListingQueryRepository",
    "BlobQueryRepository",
    "ChannelQueryRepository",
    "ChatHistoryMessage",
    "ChatHistoryQueryRepository",
    "FriendRelationshipQueryRepository",
    "LeaderboardReadScope",
    "PersonalBestQueryRepository",
    "RecalculationCandidateReason",
    "RoleQueryRepository",
    "ScoreHitCounts",
    "ScorePerformanceCandidateSelection",
    "ScorePerformanceQueryRepository",
    "ScorePerformanceRecalculationCandidate",
    "ScorePerformanceRecalculationCandidateResult",
    "ScoreQueryRepository",
    "UserQueryRepository",
    "UserStatsQueryRepository",
    "UserStatsRankInput",
    "UserStatsSourceRead",
    "UserStatsSourceRow",
]
