"""app/worker graphで共有するinfrastructure resource providerを定義する.

database, Valkey, task broker, HTTP client, state store, blob storageの具体adapterを
DishkaのAPP scopeへ配線する.
"""

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
from osu_server.infrastructure.state.interfaces.replay_download_accounting_gate import (
    ReplayDownloadAccountingGate,
)
from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
    StableUserStatusStore,
)
from osu_server.infrastructure.state.valkey.channel_state_store import ValkeyChannelStateStore
from osu_server.infrastructure.state.valkey.packet_queue import ValkeyPacketQueue
from osu_server.infrastructure.state.valkey.rate_limiter import ValkeyRateLimiter
from osu_server.infrastructure.state.valkey.replay_download_accounting_gate import (
    ValkeyReplayDownloadAccountingGate,
)
from osu_server.infrastructure.state.valkey.stable_user_status_store import (
    ValkeyStableUserStatusStore,
)
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
    ReplayDownloadAccountingGate,
    SessionStore,
    StableUserStatusStore,
    async_sessionmaker,
    httpx.AsyncClient,
)


@final
class InfrastructureProviderSet(Provider):
    """app/worker graphで共有するruntime infrastructure resourceを提供する.

    Attributes:
        scope (Scope): processの生存期間と一致するDishka scope.
        _config (AppConfig): provider生成時に保持し, config providerから返すruntime設定.
    """

    scope = Scope.APP

    def __init__(self, config: AppConfig) -> None:
        """runtime設定を保持するproviderを初期化する.

        Args:
            config (AppConfig): database, Valkey, storageなどのruntime設定.
        """
        super().__init__()
        self._config: AppConfig = config

    @provide
    def config(self) -> AppConfig:
        """Composition graphに渡されたruntime設定を提供する.

        Returns:
            AppConfig: provider生成時に保持されたruntime設定.
        """
        return self._config

    @provide
    async def engine(self, config: AppConfig) -> AsyncIterator[AsyncEngine]:
        """Database engineをAPP scope resourceとして提供する.

        Args:
            config (AppConfig): database URLを含むruntime設定.

        Yields:
            AsyncEngine: session factoryが共有するasync SQLAlchemy engine.

        Notes:
            APP scope終了時にfinally節でengineをdisposeするため, consumerは直接disposeしない.
        """
        engine = create_engine(
            str(config.database_url),
            pool_size=config.database_pool_size,
            max_overflow=config.database_max_overflow,
            pool_timeout=config.database_pool_timeout_seconds,
        )
        try:
            yield engine
        finally:
            await engine.dispose()

    @provide
    def session_factory(
        self,
        engine: AsyncEngine,
    ) -> async_sessionmaker[AsyncSession]:
        """Injected database engineに結び付くasync session factoryを提供する.

        Args:
            engine (AsyncEngine): APP scopeで所有されるSQLAlchemy engine.

        Returns:
            async_sessionmaker[AsyncSession]: Unit of Workとquery repositoryがsessionを作るfactory.
        """
        return create_session_factory(engine)

    @provide
    async def valkey(self, config: AppConfig) -> AsyncIterator[GlideClient]:
        """Valkey clientをAPP scope resourceとして接続して提供する.

        Args:
            config (AppConfig): Valkey URLを含むruntime設定.

        Yields:
            GlideClient: state store, queue, pub/sub adapterが共有するclient.

        Notes:
            APP scope終了時にfinally節でclientをcloseするため, consumerは直接closeしない.
        """
        valkey = await create_valkey_client(str(config.valkey_url))
        try:
            yield valkey
        finally:
            await valkey.close()

    @provide
    async def broker(self, config: AppConfig) -> AsyncIterator[AsyncBroker]:
        """登録済みjobを持つTaskiq brokerをAPP scope resourceとして提供する.

        Args:
            config (AppConfig): broker接続用Valkey URLを含むruntime設定.

        Yields:
            AsyncBroker: commandから非同期jobをenqueueするTaskiq broker.

        Notes:
            job登録はyield前に完了し, APP scope終了時にfinally節でbrokerをshutdownする.
        """
        broker: AsyncBroker = ListQueueBroker(url=str(config.valkey_url))
        register_all_jobs(broker)
        try:
            yield broker
        finally:
            await broker.shutdown()

    @provide
    async def http_client(self) -> AsyncIterator[httpx.AsyncClient]:
        """外部service用HTTP clientをAPP scope resourceとして提供する.

        Yields:
            httpx.AsyncClient: HIBPなどの外部HTTP adapterが共有するasync client.

        Notes:
            context managerがAPP scope終了時にclientをcloseするため, consumerは直接closeしない.
        """
        async with httpx.AsyncClient() as client:
            yield client

    @provide
    def event_bus(self) -> LocalEventBus:
        """process内event delivery用のlocal event busを提供する.

        Returns:
            LocalEventBus: durable deliveryを保証せず同一process内へeventを配信するbus.
        """
        return InMemoryLocalEventBus()

    @provide
    def packet_queue(self, valkey: GlideClient, config: AppConfig) -> PacketQueue:
        """Stable packet queue用のValkey adapterを提供する.

        Args:
            valkey (GlideClient): queue payloadを保持するshared Valkey client.
            config (AppConfig): queue上限とsession TTLを含むruntime設定.

        Returns:
            PacketQueue: user単位のpacket queueをValkeyへ保持するadapter.
        """
        return ValkeyPacketQueue(
            valkey,
            max_size=config.packet_queue_max_size,
            ttl=config.session_ttl,
        )

    @provide
    def channel_state_store(self, valkey: GlideClient) -> ChannelStateStore:
        """Channel membership state用のValkey adapterを提供する.

        Args:
            valkey (GlideClient): channel stateを保持するshared Valkey client.

        Returns:
            ChannelStateStore: volatile channel stateを読み書きするadapter.
        """
        return ValkeyChannelStateStore(valkey)

    @provide
    def stable_user_status_store(
        self,
        valkey: GlideClient,
        config: AppConfig,
    ) -> StableUserStatusStore:
        """Stable user status用のTTL付きValkey adapterを提供する.

        Args:
            valkey (GlideClient): status snapshotを保持するshared Valkey client.
            config (AppConfig): statusの有効期間として使うsession TTLを持つruntime設定.

        Returns:
            StableUserStatusStore: stable client互換のuser statusを保持するadapter.
        """
        return ValkeyStableUserStatusStore(valkey, ttl=config.session_ttl)

    @provide
    def rate_limiter(self, valkey: GlideClient) -> RateLimiter:
        """共有Valkeyを使うrate limiter adapterを提供する.

        Args:
            valkey (GlideClient): rate limit counterを保持するshared Valkey client.

        Returns:
            RateLimiter: process間でrate limit状態を共有するadapter.
        """
        return ValkeyRateLimiter(valkey)

    @provide
    def replay_download_accounting_gate(
        self,
        valkey: GlideClient,
    ) -> ReplayDownloadAccountingGate:
        """Replay download計上のidempotency gateを提供する.

        Args:
            valkey (GlideClient): replay download計上状態を保持するshared Valkey client.

        Returns:
            ReplayDownloadAccountingGate: 同一downloadの重複計上を防ぐadapter.
        """
        return ValkeyReplayDownloadAccountingGate(valkey)

    @provide
    def country_resolver(self) -> CountryResolver:
        """request由来のcountry情報を解決するCloudflare adapterを提供する.

        Returns:
            CountryResolver: Cloudflare headerを基にcountryを解決するadapter.
        """
        return CloudflareCountryResolver()

    @provide
    def hibp_client(self, http_client: httpx.AsyncClient) -> HIBPClient:
        """Have I Been Pwned照会用HTTP adapterを提供する.

        Args:
            http_client (httpx.AsyncClient): APP scopeで所有されるasync HTTP client.

        Returns:
            HIBPClient: password漏洩確認を外部serviceへ委譲するadapter.
        """
        return HTTPHIBPClient(http_client)

    @provide
    async def blob_storage_backend(self, config: AppConfig) -> BlobStorageBackend:
        """設定済みblob storage backendを検証して提供する.

        Args:
            config (AppConfig): backend種別とbackend固有設定を含むruntime設定.

        Returns:
            BlobStorageBackend: write開始前にconfiguration検証済みのphysical storage adapter.

        Raises:
            BlobStorageConfigurationError: backend種別またはstorage configurationが無効な場合.
        """
        backend = create_blob_storage_backend(config)
        await backend.validate_configuration()
        return backend

    @provide
    def session_store(self, valkey: GlideClient, config: AppConfig) -> SessionStore:
        """TTL付きactive session storeを提供する.

        Args:
            valkey (GlideClient): active sessionを保持するshared Valkey client.
            config (AppConfig): sessionの有効期間を持つruntime設定.

        Returns:
            SessionStore: process restart後も保持されるvolatile session state adapter.
        """
        return ValkeySessionStore(valkey, ttl=config.session_ttl)
