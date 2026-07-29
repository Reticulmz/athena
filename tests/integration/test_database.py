"""Database connection infrastructureが実PostgreSQLへ接続できるcontractを検証する.

Notes:
    Connection URLはDATABASE_URL environment variableから取得する.
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from tests.support.service_availability import require_tcp_service_url


def _get_database_url() -> str:
    """Integration testで使用するPostgreSQL connection URLを取得する.

    Returns:
        str: TCP接続可能なPostgreSQL URL.

    Raises:
        pytest.skip: DATABASE_URLが未設定またはTCP serviceが利用不能な場合.
    """
    return require_tcp_service_url("DATABASE_URL", default_port=5432)


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    """Integration test用のasync PostgreSQL engineを提供する.

    Yields:
        AsyncEngine: DATABASE_URLへ接続するtest engine.

    Raises:
        pytest.skip: PostgreSQL URLまたはTCP serviceが利用不能な場合.

    Notes:
        fixture終了時にengine poolをdisposeする.
    """
    eng = create_engine(_get_database_url())
    yield eng
    await eng.dispose()


class TestDatabaseEngine:
    """Async engineの生成, 接続, dispose後の再接続contractを検証する."""

    async def test_create_engine_returns_async_engine(self, engine: AsyncEngine) -> None:
        """Engine factoryがAsyncEngine instanceを返すcontractを検証する.

        Args:
            engine (AsyncEngine): fixtureが作成したPostgreSQL engine.

        Returns:
            None: returned engineのruntime type確認を完了する.
        """
        assert isinstance(engine, AsyncEngine)

    async def test_engine_connects_to_database(self, engine: AsyncEngine) -> None:
        """Async engineがPostgreSQLへ接続しsimple queryを実行するcontractを検証する.

        Args:
            engine (AsyncEngine): fixtureが作成したPostgreSQL engine.

        Returns:
            None: SELECT 1のresult確認を完了する.
        """
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    async def test_engine_dispose_closes_pool(self, engine: AsyncEngine) -> None:
        """Engine disposeがpoolをclearしてもsubsequent connectionを許可するcontractを検証する.

        Args:
            engine (AsyncEngine): fixtureが作成したPostgreSQL engine.

        Returns:
            None: dispose前後のSELECT 1成功を確認して完了する.
        """
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
    """Async session factoryの生成, query実行, driver selection contractを検証する."""

    async def test_create_session_factory_produces_sessions(self, engine: AsyncEngine) -> None:
        """Session factoryがAsyncSession instanceを生成するcontractを検証する.

        Args:
            engine (AsyncEngine): session factoryへ渡すPostgreSQL engine.

        Returns:
            None: generated sessionのruntime type確認を完了する.
        """
        factory = create_session_factory(engine)
        async with factory() as session:
            assert isinstance(session, AsyncSession)

    async def test_session_executes_query(self, engine: AsyncEngine) -> None:
        """Async sessionがPostgreSQL queryを実行するcontractを検証する.

        Args:
            engine (AsyncEngine): session factoryへ渡すPostgreSQL engine.

        Returns:
            None: SELECT 1 AS valのresult確認を完了する.
        """
        factory = create_session_factory(engine)
        async with factory() as session:
            result = await session.execute(text("SELECT 1 AS val"))
            assert result.scalar() == 1

    async def test_session_url_uses_asyncpg_driver(self, engine: AsyncEngine) -> None:
        """Test engine URLがasyncpg driverを指定するcontractを検証する.

        Args:
            engine (AsyncEngine): URLを検査するPostgreSQL engine.

        Returns:
            None: URL文字列にasyncpgが含まれることを確認して完了する.
        """
        url_str = str(engine.url)
        assert "asyncpg" in url_str
