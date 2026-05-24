# pyright: reportAny=false
"""Tests for build_container DI provider factory (TDD -- RED phase first)."""

from __future__ import annotations

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from osu_server.config import AppConfig
from osu_server.infrastructure.di.providers import build_container
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.redis.session_store import RedisSessionStore

_EXPECTED_MIN_SHUTDOWN_HOOKS = 2


def _make_config(*, environment: str = "test") -> AppConfig:
    """Create a minimal AppConfig for testing."""
    return AppConfig(
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
        environment=environment,
    )


# ---------------------------------------------------------------------------
# Test: build_container registers all expected types
# ---------------------------------------------------------------------------


async def test_build_container_registers_all_types() -> None:
    """build_container should register AsyncEngine, Redis, async_sessionmaker, SessionStore."""
    config = _make_config(environment="test")
    container = await build_container(config)

    # All four types must be resolvable without raising KeyError
    engine = await container.resolve(AsyncEngine)
    redis_client = await container.resolve(Redis)
    session_factory = await container.resolve(async_sessionmaker[AsyncSession])
    session_store = await container.resolve(SessionStore)

    assert engine is not None
    assert redis_client is not None
    assert session_factory is not None
    assert session_store is not None


# ---------------------------------------------------------------------------
# Test: test environment uses InMemorySessionStore
# ---------------------------------------------------------------------------


async def test_build_container_test_env_uses_in_memory() -> None:
    """When environment='test', SessionStore should be InMemorySessionStore."""
    config = _make_config(environment="test")
    container = await build_container(config)

    session_store = await container.resolve(SessionStore)

    assert isinstance(session_store, InMemorySessionStore)


# ---------------------------------------------------------------------------
# Test: non-test environment uses RedisSessionStore
# ---------------------------------------------------------------------------


async def test_build_container_production_uses_redis() -> None:
    """When environment='development', SessionStore should be RedisSessionStore."""
    config = _make_config(environment="development")
    container = await build_container(config)

    session_store = await container.resolve(SessionStore)

    assert isinstance(session_store, RedisSessionStore)


# ---------------------------------------------------------------------------
# Test: shutdown hooks are registered
# ---------------------------------------------------------------------------


async def test_build_container_shutdown_hooks() -> None:
    """build_container should register shutdown hooks for engine and redis cleanup."""
    config = _make_config(environment="test")
    container = await build_container(config)

    # Access internal _shutdown_hooks to verify hooks were registered
    assert len(container._shutdown_hooks) >= _EXPECTED_MIN_SHUTDOWN_HOOKS, (  # noqa: SLF001
        "Expected at least 2 shutdown hooks (engine.dispose, redis.aclose)"
    )
