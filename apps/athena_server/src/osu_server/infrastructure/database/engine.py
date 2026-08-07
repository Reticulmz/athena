"""SQLAlchemy async engineを作成するfactoryを提供するmodule.

PostgreSQL URLをasyncpg URLへ正規化し, query diagnosticsを登録する.
"""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from osu_server.infrastructure.database.query_diagnostics import install_query_diagnostics


def create_engine(database_url: str) -> AsyncEngine:
    """Database URLからasync SQLAlchemy engineを作成する.

    ``postgresql://``と``postgres://``はasyncpg driver付きURLに変換する.
    ``pool_pre_ping``を有効化し, DB restartなどでpoolに残ったstale connectionを
    checkout前に破棄できるようにする.

    Args:
        database_url (str): PostgreSQL接続URL.

    Returns:
        AsyncEngine: asyncpg driver, stale connection check, query diagnosticsを設定したengine.
    """
    url = database_url.replace("postgres://", "postgresql+asyncpg://", 1).replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
    engine = create_async_engine(url, pool_pre_ping=True)
    install_query_diagnostics(engine)
    return engine
