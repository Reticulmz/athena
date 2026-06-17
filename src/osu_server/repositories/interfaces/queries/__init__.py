"""Query repository interface package."""

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
from osu_server.repositories.interfaces.queries.users import UserQueryRepository

__all__ = [
    "BeatmapQueryRepository",
    "BeatmapScoreListingQueryRepository",
    "BlobQueryRepository",
    "ChannelQueryRepository",
    "ChatHistoryMessage",
    "ChatHistoryQueryRepository",
    "FriendRelationshipQueryRepository",
    "PersonalBestQueryRepository",
    "RecalculationCandidateReason",
    "RoleQueryRepository",
    "ScorePerformanceCandidateSelection",
    "ScorePerformanceQueryRepository",
    "ScorePerformanceRecalculationCandidate",
    "ScorePerformanceRecalculationCandidateResult",
    "ScoreQueryRepository",
    "UserQueryRepository",
]
