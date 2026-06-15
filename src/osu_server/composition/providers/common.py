"""Common provider set shared by app and worker dependency graphs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import final

import httpx
from dishka import Provider, Scope
from glide import GlideClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from taskiq import AsyncBroker
from taskiq_redis import ListQueueBroker

from osu_server.config import AppConfig
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
from osu_server.services.commands.chat import JoinChannelUseCase, LeaveChannelUseCase
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
            (self.score_crypto_service, ScoreCryptoService),
            (self.stable_score_submit_mapper, StableScoreSubmitMapper),
        ):
            _ = self.provide(source, provides=provides, scope=Scope.APP)

        self._provide_query_repositories()
        self._provide_use_cases()

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

    def blob_storage_backend(self, config: AppConfig) -> BlobStorageBackend:
        return create_blob_storage_backend(config)

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
