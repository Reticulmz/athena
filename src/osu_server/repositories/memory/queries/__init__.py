"""In-memory query repository package."""

from osu_server.repositories.memory.queries.roles import InMemoryRoleQueryRepository
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository

__all__ = [
    "InMemoryRoleQueryRepository",
    "InMemoryUserQueryRepository",
]
