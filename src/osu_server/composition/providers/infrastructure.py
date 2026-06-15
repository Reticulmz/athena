"""Shared infrastructure providers for app and worker dependency graphs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import final

import httpx
from dishka import Provider, Scope
from glide import GlideClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from taskiq import AsyncBroker
from taskiq_redis import ListQueueBroker

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.infrastructure.cache.valkey_client import create_valkey_client
from osu_server.infrastructure.country.cloudflare import CloudflareCountryResolver
from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.infrastructure.messaging.local import LocalEventBus
from osu_server.infrastructure.messaging.memory import InMemoryLocalEventBus
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
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.valkey.session_store import ValkeySessionStore

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    AsyncBroker,
    AsyncEngine,
    AsyncIterator,
    AsyncSession,
    BlobStorageBackend,
    ChannelStateStore,
    CountryResolver,
    LocalEventBus,
    GlideClient,
    HIBPClient,
    PacketQueue,
    RateLimiter,
    SessionStore,
    async_sessionmaker,
    httpx.AsyncClient,
)


@final
class InfrastructureProviderSet(Provider):
    """Providers for shared runtime infrastructure resources."""

    scope = Scope.APP

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config: AppConfig = config

    @provide
    def config(self) -> AppConfig:
        return self._config

    @provide
    async def engine(self, config: AppConfig) -> AsyncIterator[AsyncEngine]:
        engine = create_engine(str(config.database_url))
        try:
            yield engine
        finally:
            await engine.dispose()

    @provide
    def session_factory(
        self,
        engine: AsyncEngine,
    ) -> async_sessionmaker[AsyncSession]:
        return create_session_factory(engine)

    @provide
    async def valkey(self, config: AppConfig) -> AsyncIterator[GlideClient]:
        valkey = await create_valkey_client(str(config.valkey_url))
        try:
            yield valkey
        finally:
            await valkey.close()

    @provide
    async def broker(self, config: AppConfig) -> AsyncIterator[AsyncBroker]:
        broker: AsyncBroker = ListQueueBroker(url=str(config.valkey_url))
        register_all_jobs(broker)
        try:
            yield broker
        finally:
            await broker.shutdown()

    @provide
    async def http_client(self) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient() as client:
            yield client

    @provide
    def event_bus(self) -> LocalEventBus:
        return InMemoryLocalEventBus()

    @provide
    def packet_queue(self, valkey: GlideClient, config: AppConfig) -> PacketQueue:
        return ValkeyPacketQueue(
            valkey,
            max_size=config.packet_queue_max_size,
            ttl=config.session_ttl,
        )

    @provide
    def channel_state_store(self, valkey: GlideClient) -> ChannelStateStore:
        return ValkeyChannelStateStore(valkey)

    @provide
    def rate_limiter(self, valkey: GlideClient) -> RateLimiter:
        return ValkeyRateLimiter(valkey)

    @provide
    def country_resolver(self) -> CountryResolver:
        return CloudflareCountryResolver()

    @provide
    def hibp_client(self, http_client: httpx.AsyncClient) -> HIBPClient:
        return HTTPHIBPClient(http_client)

    @provide
    async def blob_storage_backend(self, config: AppConfig) -> BlobStorageBackend:
        backend = create_blob_storage_backend(config)
        await backend.validate_configuration()
        return backend

    @provide
    def session_store(self, valkey: GlideClient, config: AppConfig) -> SessionStore:
        return ValkeySessionStore(valkey, ttl=config.session_ttl)
