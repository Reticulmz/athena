# pyright: reportAny=false
"""DI provider factory — assembles the Container with infrastructure components.

Only registers components from the infrastructure layer and below.
Higher-layer registrations (repositories, services, transports) are
performed in ``app.py`` — the composition root.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from osu_server.infrastructure.cache.redis_client import create_redis_client
from osu_server.infrastructure.country.cloudflare import CloudflareCountryResolver
from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.infrastructure.di.container import Container
from osu_server.infrastructure.messaging.interfaces import EventBus
from osu_server.infrastructure.messaging.memory import InMemoryEventBus
from osu_server.infrastructure.security.hibp import HIBPClient
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.interfaces.session_store import SessionStore
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.memory.session_store import InMemorySessionStore
from osu_server.infrastructure.state.redis.packet_queue import RedisPacketQueue
from osu_server.infrastructure.state.redis.session_store import RedisSessionStore

if TYPE_CHECKING:
    from osu_server.config import AppConfig


async def build_container(config: AppConfig) -> Container:
    """Build and return a DI Container with infrastructure-layer registrations.

    Registers:
        - ``AsyncEngine`` (singleton) from ``config.database_url``
        - ``Redis`` (singleton) from ``config.redis_url``
        - ``async_sessionmaker[AsyncSession]`` (singleton) from the engine
        - ``SessionStore`` (singleton): ``InMemorySessionStore`` when
          ``config.environment == "test"``, otherwise ``RedisSessionStore``
        - ``httpx.AsyncClient`` (singleton) with shutdown hook for ``aclose()``
        - ``HIBPClient`` (singleton) using the ``httpx.AsyncClient``
        - ``CountryResolver`` (singleton): ``CloudflareCountryResolver``

    Shutdown hooks are registered for ``engine.dispose()``, ``redis.aclose()``,
    and ``http_client.aclose()``.
    """
    container = Container()

    # -- Database engine (singleton) ------------------------------------------
    engine = create_engine(str(config.database_url))
    container.register_singleton(AsyncEngine, lambda: engine)

    # -- Redis client (singleton) ---------------------------------------------
    redis = create_redis_client(str(config.redis_url))
    container.register_singleton(Redis, lambda: redis)

    # -- Session factory (singleton) ------------------------------------------
    session_factory = create_session_factory(engine)
    container.register_singleton(async_sessionmaker[AsyncSession], lambda: session_factory)

    # -- SessionStore (singleton, environment-based switching) -----------------
    if config.environment == "test":
        container.register_singleton(SessionStore, InMemorySessionStore)
    else:
        container.register_singleton(
            SessionStore,
            lambda: RedisSessionStore(redis, ttl=config.session_ttl),
        )

    # -- PacketQueue (singleton, environment-based switching) -----------------
    if config.environment == "test":
        container.register_singleton(
            PacketQueue,
            lambda: InMemoryPacketQueue(max_size=config.packet_queue_max_size),
        )
    else:
        container.register_singleton(
            PacketQueue,
            lambda: RedisPacketQueue(
                redis,
                max_size=config.packet_queue_max_size,
                ttl=config.session_ttl,
            ),
        )

    # -- EventBus (singleton) ------------------------------------------------
    container.register_singleton(EventBus, InMemoryEventBus)

    # -- httpx.AsyncClient (singleton) ----------------------------------------
    http_client = httpx.AsyncClient()
    container.register_singleton(httpx.AsyncClient, lambda: http_client)

    # -- HIBPClient (singleton) -----------------------------------------------
    hibp_client = HIBPClient(http_client)
    container.register_singleton(HIBPClient, lambda: hibp_client)

    # -- CountryResolver (singleton) ------------------------------------------
    country_resolver = CloudflareCountryResolver()
    container.register_singleton(CountryResolver, lambda: country_resolver)

    # -- Shutdown hooks -------------------------------------------------------
    container.register_shutdown_hook(engine.dispose)
    container.register_shutdown_hook(redis.aclose)
    container.register_shutdown_hook(http_client.aclose)

    return container
