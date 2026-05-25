"""Tests for build_container DI provider factory (TDD -- RED phase first)."""

from __future__ import annotations

import os

import pytest
from glide import GlideClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from osu_server.config import AppConfig
from osu_server.infrastructure.di.providers import build_container

_EXPECTED_MIN_SHUTDOWN_HOOKS = 2

_requires_valkey = pytest.mark.skipif(
    not os.environ.get("VALKEY_URL"),
    reason="VALKEY_URL not set",
)


def _make_config(*, environment: str = "test") -> AppConfig:
    """Create a minimal AppConfig for testing."""
    return AppConfig(
        database_url="postgresql://test:test@localhost:5432/test",  # pyright: ignore[reportArgumentType]
        valkey_url="redis://localhost:6379/0",  # pyright: ignore[reportArgumentType]
        environment=environment,
    )


# ---------------------------------------------------------------------------
# Test: build_container registers all expected types
# ---------------------------------------------------------------------------


@_requires_valkey
async def test_build_container_registers_all_types() -> None:
    """build_container should register AsyncEngine, GlideClient, async_sessionmaker."""
    config = _make_config(environment="test")
    container = await build_container(config)

    engine = await container.resolve(AsyncEngine)
    valkey_client = await container.resolve(GlideClient)
    session_factory = await container.resolve(async_sessionmaker[AsyncSession])

    assert engine is not None
    assert valkey_client is not None
    assert session_factory is not None

    await container.shutdown()


# ---------------------------------------------------------------------------
# Test: shutdown hooks are registered
# ---------------------------------------------------------------------------


@_requires_valkey
async def test_build_container_shutdown_hooks() -> None:
    """build_container should register shutdown hooks for engine and valkey cleanup."""
    config = _make_config(environment="test")
    container = await build_container(config)

    assert len(container._shutdown_hooks) >= _EXPECTED_MIN_SHUTDOWN_HOOKS, (  # noqa: SLF001
        "Expected at least 2 shutdown hooks (engine.dispose, valkey.close)"
    )

    await container.shutdown()
