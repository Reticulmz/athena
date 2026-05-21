# pyright: reportAny=false
"""DI provider factory — assembles the Container with all infrastructure components."""

from __future__ import annotations

from typing import TYPE_CHECKING

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from osu_server.infrastructure.cache.redis_client import create_redis_client
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.infrastructure.di.container import Container
from osu_server.infrastructure.state.interfaces.session_store import SessionStore
from osu_server.infrastructure.state.memory.session_store import InMemorySessionStore
from osu_server.infrastructure.state.redis.session_store import RedisSessionStore

if TYPE_CHECKING:
    from osu_server.config import AppConfig


async def build_container(config: AppConfig) -> Container:
    """Build and return a fully-wired DI Container.

    Registers:
        - ``AsyncEngine`` (singleton) from ``config.database_url``
        - ``Redis`` (singleton) from ``config.redis_url``
        - ``async_sessionmaker[AsyncSession]`` (singleton) from the engine
        - ``SessionStore`` (singleton): ``InMemorySessionStore`` when
          ``config.environment == "test"``, otherwise ``RedisSessionStore``

    Shutdown hooks are registered for ``engine.dispose()`` and ``redis.aclose()``.
    """
    container = Container()

    # -- Database engine (singleton) ------------------------------------------
    engine = create_engine(config.database_url)
    container.register_singleton(AsyncEngine, lambda: engine)

    # -- Redis client (singleton) ---------------------------------------------
    redis = create_redis_client(config.redis_url)
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
            lambda: RedisSessionStore(redis),
        )

    # -- Shutdown hooks -------------------------------------------------------
    container.register_shutdown_hook(engine.dispose)
    container.register_shutdown_hook(redis.aclose)

    return container
