"""SQLAlchemy query repository package."""

from osu_server.repositories.sqlalchemy.queries.beatmap_score_listing import (
    SQLAlchemyBeatmapScoreListingQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.beatmaps import SQLAlchemyBeatmapQueryRepository
from osu_server.repositories.sqlalchemy.queries.blobs import SQLAlchemyBlobQueryRepository
from osu_server.repositories.sqlalchemy.queries.channels import SQLAlchemyChannelQueryRepository
from osu_server.repositories.sqlalchemy.queries.chat import SQLAlchemyChatHistoryQueryRepository
from osu_server.repositories.sqlalchemy.queries.roles import SQLAlchemyRoleQueryRepository
from osu_server.repositories.sqlalchemy.queries.scores import SQLAlchemyScoreQueryRepository
from osu_server.repositories.sqlalchemy.queries.users import SQLAlchemyUserQueryRepository

__all__ = [
    "SQLAlchemyBeatmapQueryRepository",
    "SQLAlchemyBeatmapScoreListingQueryRepository",
    "SQLAlchemyBlobQueryRepository",
    "SQLAlchemyChannelQueryRepository",
    "SQLAlchemyChatHistoryQueryRepository",
    "SQLAlchemyRoleQueryRepository",
    "SQLAlchemyScoreQueryRepository",
    "SQLAlchemyUserQueryRepository",
]
