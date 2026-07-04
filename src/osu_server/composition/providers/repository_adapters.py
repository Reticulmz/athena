"""Repository adapter families for production and in-memory graphs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    BeatmapLeaderboardQueryRepository,
)
from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
    BeatmapScoreListingQueryRepository,
)
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.queries.blobs import BlobQueryRepository
from osu_server.repositories.interfaces.queries.channels import ChannelQueryRepository
from osu_server.repositories.interfaces.queries.chat import ChatHistoryQueryRepository
from osu_server.repositories.interfaces.queries.friends import (
    FriendRelationshipQueryRepository,
)
from osu_server.repositories.interfaces.queries.personal_bests import PersonalBestQueryRepository
from osu_server.repositories.interfaces.queries.replay_download import (
    ReplayDownloadQueryRepository,
)
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceQueryRepository,
)
from osu_server.repositories.interfaces.queries.scores import ScoreQueryRepository
from osu_server.repositories.interfaces.queries.user_stats import UserStatsQueryRepository
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.beatmap_leaderboards import (
    InMemoryBeatmapLeaderboardQueryRepository,
)
from osu_server.repositories.memory.queries.beatmap_score_listing import (
    InMemoryBeatmapScoreListingQueryRepository,
)
from osu_server.repositories.memory.queries.beatmaps import InMemoryBeatmapQueryRepository
from osu_server.repositories.memory.queries.blobs import InMemoryBlobQueryRepository
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.queries.chat import InMemoryChatHistoryQueryRepository
from osu_server.repositories.memory.queries.friends import (
    InMemoryFriendRelationshipQueryRepository,
)
from osu_server.repositories.memory.queries.personal_bests import (
    InMemoryPersonalBestQueryRepository,
)
from osu_server.repositories.memory.queries.replay_download import (
    InMemoryReplayDownloadQueryRepository,
)
from osu_server.repositories.memory.queries.roles import InMemoryRoleQueryRepository
from osu_server.repositories.memory.queries.score_performance import (
    InMemoryScorePerformanceQueryRepository,
)
from osu_server.repositories.memory.queries.scores import InMemoryScoreQueryRepository
from osu_server.repositories.memory.queries.user_stats import InMemoryUserStatsQueryRepository
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.repositories.sqlalchemy.queries.beatmap_leaderboards import (
    SQLAlchemyBeatmapLeaderboardQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.beatmap_score_listing import (
    SQLAlchemyBeatmapScoreListingQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.beatmaps import SQLAlchemyBeatmapQueryRepository
from osu_server.repositories.sqlalchemy.queries.blobs import SQLAlchemyBlobQueryRepository
from osu_server.repositories.sqlalchemy.queries.channels import SQLAlchemyChannelQueryRepository
from osu_server.repositories.sqlalchemy.queries.chat import (
    SQLAlchemyChatHistoryQueryRepository,
)
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
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class RepositoryAdapterReplacement:
    """One interface-to-adapter binding for provider replacement."""

    provides: type[object]
    value: object


class SQLAlchemyRepositoryAdapterFamily:
    """Build SQLAlchemy repository adapters from the app session factory."""

    def unit_of_work_factory(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UnitOfWorkFactory:
        return SQLAlchemyUnitOfWorkFactory(session_factory)

    def user_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UserQueryRepository:
        return SQLAlchemyUserQueryRepository(session_factory)

    def role_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> RoleQueryRepository:
        return SQLAlchemyRoleQueryRepository(session_factory)

    def channel_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ChannelQueryRepository:
        return SQLAlchemyChannelQueryRepository(session_factory)

    def chat_history_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ChatHistoryQueryRepository:
        return SQLAlchemyChatHistoryQueryRepository(session_factory)

    def beatmap_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapQueryRepository:
        return SQLAlchemyBeatmapQueryRepository(session_factory)

    def beatmap_score_listing_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapScoreListingQueryRepository:
        return SQLAlchemyBeatmapScoreListingQueryRepository(session_factory)

    def beatmap_leaderboard_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapLeaderboardQueryRepository:
        return SQLAlchemyBeatmapLeaderboardQueryRepository(session_factory)

    def blob_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BlobQueryRepository:
        return SQLAlchemyBlobQueryRepository(session_factory)

    def score_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ScoreQueryRepository:
        return SQLAlchemyScoreQueryRepository(session_factory)

    def personal_best_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> PersonalBestQueryRepository:
        return SQLAlchemyPersonalBestQueryRepository(session_factory)

    def friend_relationship_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> FriendRelationshipQueryRepository:
        return SQLAlchemyFriendRelationshipQueryRepository(session_factory)

    def score_performance_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ScorePerformanceQueryRepository:
        return SQLAlchemyScorePerformanceQueryRepository(session_factory)

    def user_stats_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UserStatsQueryRepository:
        return SQLAlchemyUserStatsQueryRepository(session_factory)

    def replay_download_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ReplayDownloadQueryRepository:
        return SQLAlchemyReplayDownloadQueryRepository(session_factory)


class InMemoryRepositoryAdapterFamily:
    """Build one coherent in-memory repository adapter set."""

    state: InMemoryCommandRepositoryState
    unit_of_work_factory: InMemoryUnitOfWorkFactory
    beatmap_query_repository: InMemoryBeatmapQueryRepository

    def __init__(self, state: InMemoryCommandRepositoryState | None = None) -> None:
        self.state = state if state is not None else InMemoryCommandRepositoryState()
        self.unit_of_work_factory = InMemoryUnitOfWorkFactory(self.state)
        self.beatmap_query_repository = InMemoryBeatmapQueryRepository(self.unit_of_work_factory)

    def replacements(self) -> tuple[RepositoryAdapterReplacement, ...]:
        """Return provider replacements for all in-memory repository adapters."""
        return (
            RepositoryAdapterReplacement(UnitOfWorkFactory, self.unit_of_work_factory),
            RepositoryAdapterReplacement(
                UserQueryRepository,
                InMemoryUserQueryRepository(self.unit_of_work_factory),
            ),
            RepositoryAdapterReplacement(
                RoleQueryRepository,
                InMemoryRoleQueryRepository(self.unit_of_work_factory),
            ),
            RepositoryAdapterReplacement(
                ChannelQueryRepository,
                InMemoryChannelQueryRepository(self.unit_of_work_factory),
            ),
            RepositoryAdapterReplacement(
                ChatHistoryQueryRepository,
                InMemoryChatHistoryQueryRepository(self.unit_of_work_factory),
            ),
            RepositoryAdapterReplacement(
                FriendRelationshipQueryRepository,
                InMemoryFriendRelationshipQueryRepository(self.unit_of_work_factory),
            ),
            RepositoryAdapterReplacement(
                BeatmapQueryRepository,
                self.beatmap_query_repository,
            ),
            RepositoryAdapterReplacement(
                BlobQueryRepository,
                InMemoryBlobQueryRepository(self.unit_of_work_factory),
            ),
            RepositoryAdapterReplacement(
                PersonalBestQueryRepository,
                InMemoryPersonalBestQueryRepository(self.unit_of_work_factory),
            ),
            RepositoryAdapterReplacement(
                ScoreQueryRepository,
                InMemoryScoreQueryRepository(self.unit_of_work_factory),
            ),
            RepositoryAdapterReplacement(
                BeatmapScoreListingQueryRepository,
                InMemoryBeatmapScoreListingQueryRepository(self.beatmap_query_repository),
            ),
            RepositoryAdapterReplacement(
                BeatmapLeaderboardQueryRepository,
                InMemoryBeatmapLeaderboardQueryRepository(self.unit_of_work_factory),
            ),
            RepositoryAdapterReplacement(
                ScorePerformanceQueryRepository,
                InMemoryScorePerformanceQueryRepository(self.unit_of_work_factory),
            ),
            RepositoryAdapterReplacement(
                UserStatsQueryRepository,
                InMemoryUserStatsQueryRepository(self.unit_of_work_factory),
            ),
            RepositoryAdapterReplacement(
                ReplayDownloadQueryRepository,
                InMemoryReplayDownloadQueryRepository(self.unit_of_work_factory),
            ),
        )


__all__ = [
    "InMemoryRepositoryAdapterFamily",
    "RepositoryAdapterReplacement",
    "SQLAlchemyRepositoryAdapterFamily",
]
