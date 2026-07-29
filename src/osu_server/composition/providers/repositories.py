"""app/worker graphで共有するSQLAlchemy repository providerを定義する.

このmoduleはrepository interfaceをproduction SQLAlchemy adapterへ結び付ける.
transaction lifecycleはinjected session factoryとUnit of Workへ委譲する.
"""

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
    ReplayDownloadQueryRepository,
    RoleQueryRepository,
    ScorePerformanceQueryRepository,
    ScoreQueryRepository,
    UnitOfWorkFactory,
    UserQueryRepository,
    UserStatsQueryRepository,
    async_sessionmaker,
)


@final
class RepositoryProviderSet(Provider):
    """Unit of Workとread-only query repositoryをproduction adapterへ配線する.

    Attributes:
        scope (Scope): app/worker processの生存期間と一致するDishka scope.
        _adapters (SQLAlchemyRepositoryAdapterFamily): interface別adapterを生成する
            stateless factory.
    """

    scope = Scope.APP
    _adapters = SQLAlchemyRepositoryAdapterFamily()

    @provide
    def unit_of_work_factory(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UnitOfWorkFactory:
        """SQLAlchemy Unit of Work factoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): command transaction用sessionを
                作るfactory.

        Returns:
            UnitOfWorkFactory: command use caseがtransaction境界を開くproduction factory.
        """
        return self._adapters.unit_of_work_factory(session_factory)

    @provide
    def user_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UserQueryRepository:
        """User read model用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            UserQueryRepository: user identityとcredential metadataを読むproduction adapter.
        """
        return self._adapters.user_query_repository(session_factory)

    @provide
    def role_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> RoleQueryRepository:
        """Role read model用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            RoleQueryRepository: roleとprivilege定義を読むproduction adapter.
        """
        return self._adapters.role_query_repository(session_factory)

    @provide
    def channel_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ChannelQueryRepository:
        """Channel read model用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            ChannelQueryRepository: channel metadataを読むproduction adapter.
        """
        return self._adapters.channel_query_repository(session_factory)

    @provide
    def chat_history_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ChatHistoryQueryRepository:
        """Chat history read model用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            ChatHistoryQueryRepository: persisted chat historyを読むproduction adapter.
        """
        return self._adapters.chat_history_query_repository(session_factory)

    @provide
    def beatmap_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapQueryRepository:
        """Beatmap read model用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            BeatmapQueryRepository: beatmap metadataとfile参照を読むproduction adapter.
        """
        return self._adapters.beatmap_query_repository(session_factory)

    @provide
    def beatmap_score_listing_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapScoreListingQueryRepository:
        """Beatmap score listing用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            BeatmapScoreListingQueryRepository: stable score listingを読むproduction adapter.
        """
        return self._adapters.beatmap_score_listing_query_repository(session_factory)

    @provide
    def beatmap_leaderboard_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapLeaderboardQueryRepository:
        """Beatmap leaderboard用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            BeatmapLeaderboardQueryRepository: beatmap ranking read modelを読むproduction adapter.
        """
        return self._adapters.beatmap_leaderboard_query_repository(session_factory)

    @provide
    def blob_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BlobQueryRepository:
        """Blob metadata用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            BlobQueryRepository: physical blobへ対応するmetadataを読むproduction adapter.
        """
        return self._adapters.blob_query_repository(session_factory)

    @provide
    def score_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ScoreQueryRepository:
        """Score read model用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            ScoreQueryRepository: submitted scoreのread modelを読むproduction adapter.
        """
        return self._adapters.score_query_repository(session_factory)

    @provide
    def personal_best_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> PersonalBestQueryRepository:
        """Personal best用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            PersonalBestQueryRepository: user別personal bestを読むproduction adapter.
        """
        return self._adapters.personal_best_query_repository(session_factory)

    @provide
    def friend_relationship_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> FriendRelationshipQueryRepository:
        """Friend relationship用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            FriendRelationshipQueryRepository: user間friend relationshipを読むproduction adapter.
        """
        return self._adapters.friend_relationship_query_repository(session_factory)

    @provide
    def score_performance_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ScorePerformanceQueryRepository:
        """Score performance用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            ScorePerformanceQueryRepository: calculation stateとperformance resultを読む
                production adapter.
        """
        return self._adapters.score_performance_query_repository(session_factory)

    @provide
    def user_stats_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UserStatsQueryRepository:
        """User statistics用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            UserStatsQueryRepository: user statistics read modelを読むproduction adapter.
        """
        return self._adapters.user_stats_query_repository(session_factory)

    @provide
    def replay_download_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ReplayDownloadQueryRepository:
        """Replay download用SQLAlchemy query repositoryを提供する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            ReplayDownloadQueryRepository: replay download対象とaccounting情報を読む
                production adapter.
        """
        return self._adapters.replay_download_query_repository(session_factory)
