"""Shared repository providers for app and worker dependency graphs."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from osu_server.composition.providers._dishka import provide
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
from osu_server.repositories.sqlalchemy.queries.roles import SQLAlchemyRoleQueryRepository
from osu_server.repositories.sqlalchemy.queries.score_performance import (
    SQLAlchemyScorePerformanceQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.scores import SQLAlchemyScoreQueryRepository
from osu_server.repositories.sqlalchemy.queries.users import SQLAlchemyUserQueryRepository
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory

_DISHKA_RUNTIME_HINTS = (
    AsyncSession,
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

    @provide
    def unit_of_work_factory(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UnitOfWorkFactory:
        return SQLAlchemyUnitOfWorkFactory(session_factory)

    @provide
    def user_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UserQueryRepository:
        return SQLAlchemyUserQueryRepository(session_factory)

    @provide
    def role_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> RoleQueryRepository:
        return SQLAlchemyRoleQueryRepository(session_factory)

    @provide
    def channel_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ChannelQueryRepository:
        return SQLAlchemyChannelQueryRepository(session_factory)

    @provide
    def chat_history_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ChatHistoryQueryRepository:
        return SQLAlchemyChatHistoryQueryRepository(session_factory)

    @provide
    def beatmap_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapQueryRepository:
        return SQLAlchemyBeatmapQueryRepository(session_factory)

    @provide
    def beatmap_score_listing_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapScoreListingQueryRepository:
        return SQLAlchemyBeatmapScoreListingQueryRepository(session_factory)

    @provide
    def blob_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BlobQueryRepository:
        return SQLAlchemyBlobQueryRepository(session_factory)

    @provide
    def score_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ScoreQueryRepository:
        return SQLAlchemyScoreQueryRepository(session_factory)

    @provide
    def personal_best_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> PersonalBestQueryRepository:
        return SQLAlchemyPersonalBestQueryRepository(session_factory)

    @provide
    def friend_relationship_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> FriendRelationshipQueryRepository:
        return SQLAlchemyFriendRelationshipQueryRepository(session_factory)

    @provide
    def score_performance_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ScorePerformanceQueryRepository:
        return SQLAlchemyScorePerformanceQueryRepository(session_factory)
