"""In-memory query repository package."""

from osu_server.repositories.memory.queries.beatmaps import InMemoryBeatmapQueryRepository
from osu_server.repositories.memory.queries.legacy_getscores import (
    InMemoryLegacyGetscoresQueryRepository,
)
from osu_server.repositories.memory.queries.roles import InMemoryRoleQueryRepository
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository

__all__ = [
    "InMemoryBeatmapQueryRepository",
    "InMemoryLegacyGetscoresQueryRepository",
    "InMemoryRoleQueryRepository",
    "InMemoryUserQueryRepository",
]
