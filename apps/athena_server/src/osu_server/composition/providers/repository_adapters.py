"""production/test graph向けrepository adapter familyを定義する.

production graphはSQLAlchemy adapterをsession factoryから生成する.
test graphは共有in-memory stateを使うadapter replacement集合を生成する.
"""

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
from osu_server.repositories.memory.queries.state import InMemoryQueryStateSnapshotProvider
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
    """provider replacement用のinterface-to-adapter bindingを表す.

    Attributes:
        provides (type[object]): replacement対象となるrepositoryまたはfactory portの型.
        value (object): portへ注入するconcrete adapter instance.
    """

    provides: type[object]
    value: object


class SQLAlchemyRepositoryAdapterFamily:
    """session factoryからproduction SQLAlchemy repository adapterを生成する.

    各methodはadapter instanceだけを生成し, sessionのcommit/rollback lifecycleは
    Unit of Workまたはrepository実装へ委譲する.
    """

    def unit_of_work_factory(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UnitOfWorkFactory:
        """SQLAlchemy Unit of Work factoryを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): command transaction用sessionを
                作るfactory.

        Returns:
            UnitOfWorkFactory: SQLAlchemy command repositoryを束ねるproduction factory.
        """
        return SQLAlchemyUnitOfWorkFactory(session_factory)

    def user_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UserQueryRepository:
        """SQLAlchemy user query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            UserQueryRepository: user identityとcredential metadataを読むadapter.
        """
        return SQLAlchemyUserQueryRepository(session_factory)

    def role_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> RoleQueryRepository:
        """SQLAlchemy role query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            RoleQueryRepository: roleとprivilege定義を読むadapter.
        """
        return SQLAlchemyRoleQueryRepository(session_factory)

    def channel_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ChannelQueryRepository:
        """SQLAlchemy channel query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            ChannelQueryRepository: channel metadataを読むadapter.
        """
        return SQLAlchemyChannelQueryRepository(session_factory)

    def chat_history_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ChatHistoryQueryRepository:
        """SQLAlchemy chat history query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            ChatHistoryQueryRepository: persisted chat historyを読むadapter.
        """
        return SQLAlchemyChatHistoryQueryRepository(session_factory)

    def beatmap_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapQueryRepository:
        """SQLAlchemy beatmap query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            BeatmapQueryRepository: beatmap metadataとfile参照を読むadapter.
        """
        return SQLAlchemyBeatmapQueryRepository(session_factory)

    def beatmap_score_listing_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapScoreListingQueryRepository:
        """SQLAlchemy beatmap score listing query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            BeatmapScoreListingQueryRepository: stable score listingを読むadapter.
        """
        return SQLAlchemyBeatmapScoreListingQueryRepository(session_factory)

    def beatmap_leaderboard_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapLeaderboardQueryRepository:
        """SQLAlchemy beatmap leaderboard query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            BeatmapLeaderboardQueryRepository: beatmap ranking read modelを読むadapter.
        """
        return SQLAlchemyBeatmapLeaderboardQueryRepository(session_factory)

    def blob_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BlobQueryRepository:
        """SQLAlchemy blob metadata query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            BlobQueryRepository: physical blobへ対応するmetadataを読むadapter.
        """
        return SQLAlchemyBlobQueryRepository(session_factory)

    def score_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ScoreQueryRepository:
        """SQLAlchemy score query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            ScoreQueryRepository: submitted scoreのread modelを読むadapter.
        """
        return SQLAlchemyScoreQueryRepository(session_factory)

    def personal_best_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> PersonalBestQueryRepository:
        """SQLAlchemy personal best query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            PersonalBestQueryRepository: user別personal bestを読むadapter.
        """
        return SQLAlchemyPersonalBestQueryRepository(session_factory)

    def friend_relationship_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> FriendRelationshipQueryRepository:
        """SQLAlchemy friend relationship query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            FriendRelationshipQueryRepository: user間friend relationshipを読むadapter.
        """
        return SQLAlchemyFriendRelationshipQueryRepository(session_factory)

    def score_performance_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ScorePerformanceQueryRepository:
        """SQLAlchemy score performance query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            ScorePerformanceQueryRepository: calculation stateとperformance resultを読むadapter.
        """
        return SQLAlchemyScorePerformanceQueryRepository(session_factory)

    def user_stats_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UserStatsQueryRepository:
        """SQLAlchemy user statistics query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            UserStatsQueryRepository: user statistics read modelを読むadapter.
        """
        return SQLAlchemyUserStatsQueryRepository(session_factory)

    def replay_download_query_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ReplayDownloadQueryRepository:
        """SQLAlchemy replay download query adapterを生成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            ReplayDownloadQueryRepository: replay download対象とaccounting情報を読むadapter.
        """
        return SQLAlchemyReplayDownloadQueryRepository(session_factory)


class InMemoryRepositoryAdapterFamily:
    """test graph向けに共有stateを持つin-memory repository adapterを生成する.

    Attributes:
        state (InMemoryCommandRepositoryState): 全command/query adapterが共有するdurable state代替.
        unit_of_work_factory (InMemoryUnitOfWorkFactory): shared stateを更新するin-memory
            transaction factory.
        query_state_snapshot_provider (InMemoryQueryStateSnapshotProvider): read adapterへ
            state snapshotを渡すprovider.
        beatmap_query_repository (InMemoryBeatmapQueryRepository): score listing adapterとも
            共有するbeatmap query adapter.
    """

    state: InMemoryCommandRepositoryState
    unit_of_work_factory: InMemoryUnitOfWorkFactory
    query_state_snapshot_provider: InMemoryQueryStateSnapshotProvider
    beatmap_query_repository: InMemoryBeatmapQueryRepository

    def __init__(self, state: InMemoryCommandRepositoryState | None = None) -> None:
        """Shared stateに結び付くin-memory adapter familyを初期化する.

        Args:
            state (InMemoryCommandRepositoryState | None): 既存shared state. Noneの場合は
                新しいstateを作る.

        Notes:
            replacementで返す全adapterはこのinstanceのUnit of Workまたはsnapshot providerを
                共有する.
        """
        self.state = state if state is not None else InMemoryCommandRepositoryState()
        self.unit_of_work_factory = InMemoryUnitOfWorkFactory(self.state)
        self.query_state_snapshot_provider = InMemoryQueryStateSnapshotProvider(self.state)
        self.beatmap_query_repository = InMemoryBeatmapQueryRepository(self.unit_of_work_factory)

    def replacements(self) -> tuple[RepositoryAdapterReplacement, ...]:
        """in-memory repository adapter用provider replacementを返す.

        Returns:
            tuple[RepositoryAdapterReplacement, ...]: test containerへ渡す全repository/factory
                portのbinding.

        Notes:
            各bindingは同じshared stateを参照し, production SQLAlchemy providerを置換する.
        """
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
                InMemoryReplayDownloadQueryRepository(self.query_state_snapshot_provider),
            ),
        )


__all__ = [
    "InMemoryRepositoryAdapterFamily",
    "RepositoryAdapterReplacement",
    "SQLAlchemyRepositoryAdapterFamily",
]
