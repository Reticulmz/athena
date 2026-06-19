"""SQLAlchemy command repository package."""

from osu_server.repositories.interfaces.commands.blobs import DuplicateBlobError
from osu_server.repositories.sqlalchemy.commands.beatmap_leaderboards import (
    SQLAlchemyBeatmapLeaderboardCommandRepository,
)
from osu_server.repositories.sqlalchemy.commands.beatmaps import (
    BeatmapNotFoundError,
    DuplicateBeatmapChecksumError,
    SQLAlchemyBeatmapCommandRepository,
)
from osu_server.repositories.sqlalchemy.commands.blobs import SQLAlchemyBlobCommandRepository
from osu_server.repositories.sqlalchemy.commands.channels import SQLAlchemyChannelCommandRepository
from osu_server.repositories.sqlalchemy.commands.chat import SQLAlchemyChatCommandRepository
from osu_server.repositories.sqlalchemy.commands.friends import (
    SQLAlchemyFriendRelationshipCommandRepository,
)
from osu_server.repositories.sqlalchemy.commands.personal_bests import (
    SQLAlchemyPersonalBestCommandRepository,
)
from osu_server.repositories.sqlalchemy.commands.replays import SQLAlchemyReplayCommandRepository
from osu_server.repositories.sqlalchemy.commands.roles import SQLAlchemyRoleCommandRepository
from osu_server.repositories.sqlalchemy.commands.score_performance import (
    SQLAlchemyScorePerformanceCommandRepository,
)
from osu_server.repositories.sqlalchemy.commands.scores import SQLAlchemyScoreCommandRepository
from osu_server.repositories.sqlalchemy.commands.submissions import (
    SQLAlchemyScoreSubmissionCommandRepository,
)
from osu_server.repositories.sqlalchemy.commands.users import SQLAlchemyUserCommandRepository

__all__ = [
    "BeatmapNotFoundError",
    "DuplicateBeatmapChecksumError",
    "DuplicateBlobError",
    "SQLAlchemyBeatmapCommandRepository",
    "SQLAlchemyBeatmapLeaderboardCommandRepository",
    "SQLAlchemyBlobCommandRepository",
    "SQLAlchemyChannelCommandRepository",
    "SQLAlchemyChatCommandRepository",
    "SQLAlchemyFriendRelationshipCommandRepository",
    "SQLAlchemyPersonalBestCommandRepository",
    "SQLAlchemyReplayCommandRepository",
    "SQLAlchemyRoleCommandRepository",
    "SQLAlchemyScoreCommandRepository",
    "SQLAlchemyScorePerformanceCommandRepository",
    "SQLAlchemyScoreSubmissionCommandRepository",
    "SQLAlchemyUserCommandRepository",
]
