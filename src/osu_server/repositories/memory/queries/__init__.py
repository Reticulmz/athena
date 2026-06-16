"""In-memory query repository package."""

from osu_server.repositories.memory.queries.beatmap_score_listing import (
    InMemoryBeatmapScoreListingQueryRepository,
)
from osu_server.repositories.memory.queries.beatmaps import InMemoryBeatmapQueryRepository
from osu_server.repositories.memory.queries.blobs import InMemoryBlobQueryRepository
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.queries.chat import InMemoryChatHistoryQueryRepository
from osu_server.repositories.memory.queries.roles import InMemoryRoleQueryRepository
from osu_server.repositories.memory.queries.score_performance import (
    InMemoryScorePerformanceQueryRepository,
)
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository

__all__ = [
    "InMemoryBeatmapQueryRepository",
    "InMemoryBeatmapScoreListingQueryRepository",
    "InMemoryBlobQueryRepository",
    "InMemoryChannelQueryRepository",
    "InMemoryChatHistoryQueryRepository",
    "InMemoryRoleQueryRepository",
    "InMemoryScorePerformanceQueryRepository",
    "InMemoryUserQueryRepository",
]
