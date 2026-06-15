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
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.scores import ScoreQueryRepository
from osu_server.repositories.interfaces.queries.users import UserQueryRepository

__all__ = [
    "BeatmapQueryRepository",
    "BeatmapScoreListingQueryRepository",
    "BlobQueryRepository",
    "ChannelQueryRepository",
    "ChatHistoryMessage",
    "ChatHistoryQueryRepository",
    "RoleQueryRepository",
    "ScoreQueryRepository",
    "UserQueryRepository",
]
