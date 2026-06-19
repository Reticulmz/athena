"""Shared repository providers for app and worker dependency graphs."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from osu_server.composition.providers._dishka import provide
from osu_server.composition.providers.repository_adapters import (
    SQLAlchemyRepositoryAdapterFamily,
)
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
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceQueryRepository,
)
from osu_server.repositories.interfaces.queries.scores import ScoreQueryRepository
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_DISHKA_RUNTIME_HINTS = (
    AsyncSession,
    BeatmapLeaderboardQueryRepository,
    BeatmapQueryRepository,
    BeatmapScoreListingQueryRepository,
    BlobQueryRepository,
    ChannelQueryRepository,
    ChatHistoryQueryRepository,
    FriendRelationshipQueryRepository,
    PersonalBestQueryRepository,
    RoleQueryRepository,
    ScorePerformanceQueryRepository,
    ScoreQueryRepository,
    UnitOfWorkFactory,
    UserQueryRepository,
    async_sessionmaker,
)


@final
class RepositoryProviderSet(Provider):
    """Providers for Unit of Work and read-only query repositories."""

    scope = Scope.APP
    _adapters = SQLAlchemyRepositoryAdapterFamily()

    @provide
    def unit_of_work_factory(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UnitOfWorkFactory:
        return self._adapters.unit_of_work_factory(session_factory)

    @provide
    def user_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UserQueryRepository:
        return self._adapters.user_query_repository(session_factory)

    @provide
    def role_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> RoleQueryRepository:
        return self._adapters.role_query_repository(session_factory)

    @provide
    def channel_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ChannelQueryRepository:
        return self._adapters.channel_query_repository(session_factory)

    @provide
    def chat_history_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ChatHistoryQueryRepository:
        return self._adapters.chat_history_query_repository(session_factory)

    @provide
    def beatmap_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapQueryRepository:
        return self._adapters.beatmap_query_repository(session_factory)

    @provide
    def beatmap_score_listing_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapScoreListingQueryRepository:
        return self._adapters.beatmap_score_listing_query_repository(session_factory)

    @provide
    def beatmap_leaderboard_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapLeaderboardQueryRepository:
        return self._adapters.beatmap_leaderboard_query_repository(session_factory)

    @provide
    def blob_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BlobQueryRepository:
        return self._adapters.blob_query_repository(session_factory)

    @provide
    def score_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ScoreQueryRepository:
        return self._adapters.score_query_repository(session_factory)

    @provide
    def personal_best_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> PersonalBestQueryRepository:
        return self._adapters.personal_best_query_repository(session_factory)

    @provide
    def friend_relationship_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> FriendRelationshipQueryRepository:
        return self._adapters.friend_relationship_query_repository(session_factory)

    @provide
    def score_performance_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ScorePerformanceQueryRepository:
        return self._adapters.score_performance_query_repository(session_factory)
