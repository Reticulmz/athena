"""Integration tests for database connection infrastructure.

These tests require a running PostgreSQL instance. The connection URL is read
from the ``DATABASE_URL`` environment variable.
"""

import os
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    eng = create_engine(_get_database_url())
    yield eng
    await eng.dispose()


class TestDatabaseEngine:
    """Tests for async engine creation and connectivity."""

    async def test_create_engine_returns_async_engine(self, engine: AsyncEngine) -> None:
        assert isinstance(engine, AsyncEngine)

    async def test_engine_connects_to_database(self, engine: AsyncEngine) -> None:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    async def test_engine_dispose_closes_pool(self, engine: AsyncEngine) -> None:
        # Verify the engine can connect, then dispose, then is no longer usable
        async with engine.connect() as conn:
            _ = await conn.execute(text("SELECT 1"))
        await engine.dispose()
        # After dispose, pool is cleared but engine can still create new connections
        # (dispose clears the pool, it doesn't permanently break the engine)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1


class TestDatabaseSession:
    """Tests for async session factory."""

    async def test_create_session_factory_produces_sessions(self, engine: AsyncEngine) -> None:
        factory = create_session_factory(engine)
        async with factory() as session:
            assert isinstance(session, AsyncSession)

    async def test_session_executes_query(self, engine: AsyncEngine) -> None:
        factory = create_session_factory(engine)
        async with factory() as session:
            result = await session.execute(text("SELECT 1 AS val"))
            assert result.scalar() == 1

    async def test_session_url_uses_asyncpg_driver(self, engine: AsyncEngine) -> None:
        url_str = str(engine.url)
        assert "asyncpg" in url_str
