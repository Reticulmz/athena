"""SQLAlchemy async engineを作成するfactoryを提供するmodule.

PostgreSQL URLをasyncpg URLへ正規化し, query diagnosticsを登録する.
"""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from osu_server.infrastructure.database.query_diagnostics import install_query_diagnostics


def create_engine(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: float = 30.0,
) -> AsyncEngine:
    """Database URLからasync SQLAlchemy engineを作成する.

    ``postgresql://``と``postgres://``はasyncpg driver付きURLに変換する.
    ``pool_pre_ping``を有効化し, DB restartなどでpoolに残ったstale connectionを
    checkout前に破棄できるようにする.

    Args:
        database_url (str): PostgreSQL接続URL.
        pool_size (int): poolに保持する通常connection数.
        max_overflow (int): pool_sizeを超えて一時的に許可するconnection数.
        pool_timeout (float): connection checkoutを待つ最大秒数.

    Returns:
        AsyncEngine: asyncpg driver, stale connection check, query diagnosticsを設定したengine.
    """
    url = database_url.replace("postgres://", "postgresql+asyncpg://", 1).replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
    engine = create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
    )
    install_query_diagnostics(engine)
    return engine
