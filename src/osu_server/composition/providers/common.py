"""Common provider set shared by app and worker dependency graphs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import final

import httpx
from dishka import Provider, Scope
from glide import GlideClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from taskiq import AsyncBroker
from taskiq_redis import ListQueueBroker

from osu_server.config import AppConfig
from osu_server.domain.beatmaps import (
    BeatmapFileProvider,
    BeatmapFreshnessPolicy,
    BeatmapMetadataProvider,
)
from osu_server.infrastructure.cache.valkey_client import create_valkey_client
from osu_server.infrastructure.country.cloudflare import CloudflareCountryResolver
from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.crypto import ScoreCryptoService
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.infrastructure.messaging.interfaces import EventBus
from osu_server.infrastructure.messaging.memory import InMemoryEventBus
from osu_server.infrastructure.parsers.multipart_parser import MultipartLimits
from osu_server.infrastructure.security.hibp import HIBPClient, HTTPHIBPClient
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.infrastructure.state.valkey.channel_state_store import ValkeyChannelStateStore
from osu_server.infrastructure.state.valkey.packet_queue import ValkeyPacketQueue
from osu_server.infrastructure.state.valkey.rate_limiter import ValkeyRateLimiter
from osu_server.infrastructure.storage import create_blob_storage_backend
from osu_server.infrastructure.storage.interfaces import BlobStorageBackend
from osu_server.jobs import register_all_jobs
from osu_server.repositories.beatmaps.metadata_providers import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.repositories.interfaces.beatmap_repository import BeatmapRepository
from osu_server.repositories.interfaces.blob_repository import BlobRepository
from osu_server.repositories.interfaces.channel_repository import ChannelRepository
from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
    BeatmapScoreListingQueryRepository,
)
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.queries.blobs import BlobQueryRepository
from osu_server.repositories.interfaces.queries.channels import ChannelQueryRepository
from osu_server.repositories.interfaces.queries.chat import ChatHistoryQueryRepository
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.scores import ScoreQueryRepository
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.replay_repository import ReplayRepository
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.interfaces.score_repository import ScoreRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.submission_repository import ScoreSubmissionRepository
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.repositories.interfaces.user_repository import UserRepository
from osu_server.repositories.sqlalchemy.beatmap_repository import SQLAlchemyBeatmapRepository
from osu_server.repositories.sqlalchemy.blob_repository import SQLAlchemyBlobRepository
from osu_server.repositories.sqlalchemy.channel_repository import SQLAlchemyChannelRepository
from osu_server.repositories.sqlalchemy.queries.beatmap_score_listing import (
    SQLAlchemyBeatmapScoreListingQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.beatmaps import SQLAlchemyBeatmapQueryRepository
from osu_server.repositories.sqlalchemy.queries.blobs import SQLAlchemyBlobQueryRepository
from osu_server.repositories.sqlalchemy.queries.channels import SQLAlchemyChannelQueryRepository
from osu_server.repositories.sqlalchemy.queries.chat import (
    SQLAlchemyChatHistoryQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.roles import SQLAlchemyRoleQueryRepository
from osu_server.repositories.sqlalchemy.queries.scores import SQLAlchemyScoreQueryRepository
from osu_server.repositories.sqlalchemy.queries.users import SQLAlchemyUserQueryRepository
from osu_server.repositories.sqlalchemy.replay_repository import SQLAlchemyReplayRepository
from osu_server.repositories.sqlalchemy.role_repository import SQLAlchemyRoleRepository
from osu_server.repositories.sqlalchemy.score_repository import SQLAlchemyScoreRepository
from osu_server.repositories.sqlalchemy.submission_repository import (
    SQLAlchemyScoreSubmissionRepository,
)
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory
from osu_server.repositories.sqlalchemy.user_repository import SQLAlchemyUserRepository
from osu_server.repositories.valkey.session_store import ValkeySessionStore
from osu_server.services.beatmap_mirror import (
    BeatmapEligibilityService,
    BeatmapFileProviderService,
    MirrorMetadataProviderService,
    OsuApiMetadataProviderService,
)
from osu_server.services.blob_storage_service import BlobStorageService
from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
)
from osu_server.services.commands.chat import (
    JoinChannelUseCase,
    LeaveChannelUseCase,
    PersistChannelMessageUseCase,
    PersistPrivateMessageUseCase,
)
from osu_server.services.queries.beatmaps import (
    ResolveBeatmapByChecksumQuery,
    ResolveBeatmapByIdQuery,
)
from osu_server.services.queries.chat import (
    ListAutojoinChannelsQuery,
    ListChannelMessagesQuery,
    ListPrivateMessagesQuery,
    ListVisibleChannelsQuery,
    ResolveChannelMessageDeliveryQuery,
)
from osu_server.services.queries.scores import BeatmapScoreListingQuery
from osu_server.transports.stable.web_legacy.mappers import StableScoreSubmitMapper

# Dishka evaluates provider return annotations at runtime.
_DISHKA_RUNTIME_HINTS = (AsyncIterator,)


@final
class CommonProviderSet(Provider):
    """Common providers shared by app and worker composition graphs."""

    def __init__(self, config: AppConfig) -> None:
        super().__init__(scope=Scope.APP)
        self._config: AppConfig = config

        for source, provides in (
            (self.config, AppConfig),
            (self.engine, AsyncEngine),
            (self.session_factory, async_sessionmaker[AsyncSession]),
            (self.valkey, GlideClient),
            (self.broker, AsyncBroker),
            (self.http_client, httpx.AsyncClient),
            (self.event_bus, EventBus),
            (self.packet_queue, PacketQueue),
            (self.channel_state_store, ChannelStateStore),
            (self.rate_limiter, RateLimiter),
            (self.country_resolver, CountryResolver),
            (self.hibp_client, HIBPClient),
            (self.blob_storage_backend, BlobStorageBackend),
            (self.session_store, SessionStore),
            (self.unit_of_work_factory, UnitOfWorkFactory),
            (self.blob_storage_service, BlobStorageService),
            (self.beatmap_freshness_policy, BeatmapFreshnessPolicy),
            (self.beatmap_metadata_provider, BeatmapMetadataProvider),
            (self.beatmap_file_provider, BeatmapFileProvider),
            (self.beatmap_eligibility_service, BeatmapEligibilityService),
            (self.score_crypto_service, ScoreCryptoService),
            (self.stable_score_submit_mapper, StableScoreSubmitMapper),
        ):
            _ = self.provide(source, provides=provides, scope=Scope.APP)

        self._provide_command_repositories()
        self._provide_query_repositories()
        self._provide_use_cases()

    def _provide_command_repositories(self) -> None:
        for source, provides in (
            (self.user_repository, UserRepository),
            (self.role_repository, RoleRepository),
            (self.channel_repository, ChannelRepository),
            (self.beatmap_repository, BeatmapRepository),
            (self.blob_repository, BlobRepository),
            (self.score_repository, ScoreRepository),
            (self.replay_repository, ReplayRepository),
            (self.score_submission_repository, ScoreSubmissionRepository),
        ):
            _ = self.provide(source, provides=provides, scope=Scope.APP)

    def _provide_query_repositories(self) -> None:
        for source, provides in (
            (self.user_query_repository, UserQueryRepository),
            (self.role_query_repository, RoleQueryRepository),
            (self.channel_query_repository, ChannelQueryRepository),
            (self.chat_history_query_repository, ChatHistoryQueryRepository),
            (self.beatmap_query_repository, BeatmapQueryRepository),
            (self.beatmap_score_listing_query_repository, BeatmapScoreListingQueryRepository),
            (self.blob_query_repository, BlobQueryRepository),
            (self.score_query_repository, ScoreQueryRepository),
        ):
            _ = self.provide(source, provides=provides, scope=Scope.APP)

    def _provide_use_cases(self) -> None:
        for source, provides in (
            (self.resolve_beatmap_by_id_query, ResolveBeatmapByIdQuery),
            (self.resolve_beatmap_by_checksum_query, ResolveBeatmapByChecksumQuery),
            (self.beatmap_score_listing_query, BeatmapScoreListingQuery),
            (self.list_visible_channels_query, ListVisibleChannelsQuery),
            (self.list_autojoin_channels_query, ListAutojoinChannelsQuery),
            (self.resolve_channel_message_delivery_query, ResolveChannelMessageDeliveryQuery),
            (self.list_channel_messages_query, ListChannelMessagesQuery),
            (self.list_private_messages_query, ListPrivateMessagesQuery),
            (self.join_channel_use_case, JoinChannelUseCase),
            (self.leave_channel_use_case, LeaveChannelUseCase),
            (self.persist_channel_message_use_case, PersistChannelMessageUseCase),
            (self.persist_private_message_use_case, PersistPrivateMessageUseCase),
            (self.fetch_beatmap_metadata_use_case, FetchBeatmapMetadataUseCase),
            (self.fetch_beatmap_file_use_case, FetchBeatmapFileUseCase),
        ):
            _ = self.provide(source, provides=provides, scope=Scope.APP)

    def config(self) -> AppConfig:
        return self._config

    async def engine(self, config: AppConfig) -> AsyncIterator[AsyncEngine]:
        engine = create_engine(str(config.database_url))
        try:
            yield engine
        finally:
            await engine.dispose()

    def session_factory(
        self,
        engine: AsyncEngine,
    ) -> async_sessionmaker[AsyncSession]:
        return create_session_factory(engine)

    async def valkey(self, config: AppConfig) -> AsyncIterator[GlideClient]:
        valkey = await create_valkey_client(str(config.valkey_url))
        try:
            yield valkey
        finally:
            await valkey.close()

    async def broker(self, config: AppConfig) -> AsyncIterator[AsyncBroker]:
        broker: AsyncBroker = ListQueueBroker(url=str(config.valkey_url))
        register_all_jobs(broker)
        try:
            yield broker
        finally:
            await broker.shutdown()

    async def http_client(self) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient() as client:
            yield client

    def event_bus(self) -> EventBus:
        return InMemoryEventBus()

    def packet_queue(self, valkey: GlideClient, config: AppConfig) -> PacketQueue:
        return ValkeyPacketQueue(
            valkey,
            max_size=config.packet_queue_max_size,
            ttl=config.session_ttl,
        )

    def channel_state_store(self, valkey: GlideClient) -> ChannelStateStore:
        return ValkeyChannelStateStore(valkey)

    def rate_limiter(self, valkey: GlideClient) -> RateLimiter:
        return ValkeyRateLimiter(valkey)

    def country_resolver(self) -> CountryResolver:
        return CloudflareCountryResolver()

    def hibp_client(self, http_client: httpx.AsyncClient) -> HIBPClient:
        return HTTPHIBPClient(http_client)

    async def blob_storage_backend(self, config: AppConfig) -> BlobStorageBackend:
        backend = create_blob_storage_backend(config)
        await backend.validate_configuration()
        return backend

    def session_store(self, valkey: GlideClient, config: AppConfig) -> SessionStore:
        return ValkeySessionStore(valkey, ttl=config.session_ttl)

    def unit_of_work_factory(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UnitOfWorkFactory:
        return SQLAlchemyUnitOfWorkFactory(session_factory)

    def blob_storage_service(
        self,
        blob_repo: BlobRepository,
        backend: BlobStorageBackend,
        config: AppConfig,
    ) -> BlobStorageService:
        return BlobStorageService(
            blob_repo=blob_repo,
            backend=backend,
            storage_backend=config.blob_storage_backend,
        )

    def beatmap_freshness_policy(self, config: AppConfig) -> BeatmapFreshnessPolicy:
        return BeatmapFreshnessPolicy(
            ranked_refresh_interval=timedelta(
                seconds=config.beatmap_ranked_refresh_interval_seconds
            ),
            pending_refresh_interval=timedelta(
                seconds=config.beatmap_pending_refresh_interval_seconds
            ),
            graveyard_refresh_interval=timedelta(
                seconds=config.beatmap_graveyard_refresh_interval_seconds
            ),
            mirror_refresh_interval=timedelta(
                seconds=config.beatmap_mirror_refresh_interval_seconds
            ),
        )

    def beatmap_metadata_provider(self, config: AppConfig) -> BeatmapMetadataProvider:
        official = OsuApiMetadataProviderService(
            client_id=config.beatmap_official_api_client_id,  # pyright: ignore[reportArgumentType]
            client_secret=config.beatmap_official_api_client_secret,  # pyright: ignore[reportArgumentType]
        )
        mirror = MirrorMetadataProviderService(
            base_urls=config.beatmap_metadata_mirror_base_urls,
        )
        return CompositeBeatmapMetadataProvider(official=official, mirror=mirror)

    def beatmap_file_provider(self, config: AppConfig) -> BeatmapFileProvider:
        return BeatmapFileProviderService(
            osu_current_url_template=config.beatmap_osu_current_url_template,
            osu_legacy_url_template=config.beatmap_osu_legacy_url_template,
            mirror_url_templates=list(config.beatmap_community_mirror_url_templates),
        )

    def beatmap_eligibility_service(self) -> BeatmapEligibilityService:
        return BeatmapEligibilityService()

    def score_crypto_service(self) -> ScoreCryptoService:
        return ScoreCryptoService()

    def stable_score_submit_mapper(self, config: AppConfig) -> StableScoreSubmitMapper:
        return StableScoreSubmitMapper(
            limits=MultipartLimits(
                total_body_size=config.max_request_body_size,
                replay_size=config.score_submit_max_replay_size,
                text_field_size=config.score_submit_max_text_field_size,
            )
        )

    def user_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> UserRepository:
        return SQLAlchemyUserRepository(session_factory)

    def role_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> RoleRepository:
        return SQLAlchemyRoleRepository(session_factory)

    def channel_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ChannelRepository:
        return SQLAlchemyChannelRepository(session_factory)

    def beatmap_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BeatmapRepository:
        return SQLAlchemyBeatmapRepository(session_factory)

    def blob_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> BlobRepository:
        return SQLAlchemyBlobRepository(session_factory)

    def score_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ScoreRepository:
        return SQLAlchemyScoreRepository(session_factory)

    def replay_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ReplayRepository:
        return SQLAlchemyReplayRepository(session_factory)

    def score_submission_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ScoreSubmissionRepository:
        return SQLAlchemyScoreSubmissionRepository(session_factory)

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

    def resolve_beatmap_by_id_query(
        self,
        repository: BeatmapQueryRepository,
    ) -> ResolveBeatmapByIdQuery:
        return ResolveBeatmapByIdQuery(repository)

    def resolve_beatmap_by_checksum_query(
        self,
        repository: BeatmapQueryRepository,
    ) -> ResolveBeatmapByChecksumQuery:
        return ResolveBeatmapByChecksumQuery(repository)

    def beatmap_score_listing_query(
        self,
        repository: BeatmapScoreListingQueryRepository,
    ) -> BeatmapScoreListingQuery:
        return BeatmapScoreListingQuery(repository)

    def list_visible_channels_query(
        self,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> ListVisibleChannelsQuery:
        return ListVisibleChannelsQuery(
            channel_repository=channel_repository,
            channel_state=channel_state,
        )

    def list_autojoin_channels_query(
        self,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> ListAutojoinChannelsQuery:
        return ListAutojoinChannelsQuery(
            channel_repository=channel_repository,
            channel_state=channel_state,
        )

    def resolve_channel_message_delivery_query(
        self,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> ResolveChannelMessageDeliveryQuery:
        return ResolveChannelMessageDeliveryQuery(
            channel_repository=channel_repository,
            channel_state=channel_state,
        )

    def list_channel_messages_query(
        self,
        repository: ChatHistoryQueryRepository,
    ) -> ListChannelMessagesQuery:
        return ListChannelMessagesQuery(repository)

    def list_private_messages_query(
        self,
        repository: ChatHistoryQueryRepository,
    ) -> ListPrivateMessagesQuery:
        return ListPrivateMessagesQuery(repository)

    def join_channel_use_case(
        self,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> JoinChannelUseCase:
        return JoinChannelUseCase(
            channel_repository=channel_repository,
            channel_state=channel_state,
        )

    def leave_channel_use_case(self, channel_state: ChannelStateStore) -> LeaveChannelUseCase:
        return LeaveChannelUseCase(channel_state=channel_state)

    def persist_channel_message_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
    ) -> PersistChannelMessageUseCase:
        return PersistChannelMessageUseCase(uow_factory=uow_factory)

    def persist_private_message_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
    ) -> PersistPrivateMessageUseCase:
        return PersistPrivateMessageUseCase(uow_factory=uow_factory)

    def fetch_beatmap_metadata_use_case(
        self,
        repository: BeatmapRepository,
        metadata_provider: BeatmapMetadataProvider,
    ) -> FetchBeatmapMetadataUseCase:
        return FetchBeatmapMetadataUseCase(
            repository=repository,
            metadata_provider=metadata_provider,
        )

    def fetch_beatmap_file_use_case(
        self,
        repository: BeatmapRepository,
        file_provider: BeatmapFileProvider,
        blob_storage: BlobStorageService,
    ) -> FetchBeatmapFileUseCase:
        return FetchBeatmapFileUseCase(
            repository=repository,
            file_provider=file_provider,
            blob_storage=blob_storage,
        )
