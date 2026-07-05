"""SQLAlchemy query repository package."""

from osu_server.repositories.sqlalchemy.queries.beatmap_leaderboards import (
    SQLAlchemyBeatmapLeaderboardQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.beatmap_score_listing import (
    SQLAlchemyBeatmapScoreListingQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.beatmaps import SQLAlchemyBeatmapQueryRepository
from osu_server.repositories.sqlalchemy.queries.blobs import SQLAlchemyBlobQueryRepository
from osu_server.repositories.sqlalchemy.queries.channels import SQLAlchemyChannelQueryRepository
from osu_server.repositories.sqlalchemy.queries.chat import SQLAlchemyChatHistoryQueryRepository
from osu_server.repositories.sqlalchemy.queries.friends import (
    SQLAlchemyFriendRelationshipQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.personal_bests import (
    SQLAlchemyPersonalBestQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.replay_download import (
    SQLAlchemyReplayDownloadQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.roles import SQLAlchemyRoleQueryRepository
from osu_server.repositories.sqlalchemy.queries.score_performance import (
    SQLAlchemyScorePerformanceQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.scores import SQLAlchemyScoreQueryRepository
from osu_server.repositories.sqlalchemy.queries.user_stats import (
    SQLAlchemyUserStatsQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.users import SQLAlchemyUserQueryRepository

__all__ = [
    "SQLAlchemyBeatmapLeaderboardQueryRepository",
    "SQLAlchemyBeatmapQueryRepository",
    "SQLAlchemyBeatmapScoreListingQueryRepository",
    "SQLAlchemyBlobQueryRepository",
    "SQLAlchemyChannelQueryRepository",
    "SQLAlchemyChatHistoryQueryRepository",
    "SQLAlchemyFriendRelationshipQueryRepository",
    "SQLAlchemyPersonalBestQueryRepository",
    "SQLAlchemyReplayDownloadQueryRepository",
    "SQLAlchemyRoleQueryRepository",
    "SQLAlchemyScorePerformanceQueryRepository",
    "SQLAlchemyScoreQueryRepository",
    "SQLAlchemyUserQueryRepository",
    "SQLAlchemyUserStatsQueryRepository",
]
