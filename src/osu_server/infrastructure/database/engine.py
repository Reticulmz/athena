"""SQLAlchemy async engine factory."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    """Database URL から async SQLAlchemy engine を作成する。

    ``postgresql://`` と ``postgres://`` は asyncpg driver 付き URL に変換する。
    ``pool_pre_ping`` を有効化し、DB restart などで pool に残った stale connection
    を checkout 前に破棄できるようにする。

    Args:
        database_url: PostgreSQL connection URL.

    Returns:
        asyncpg driver と stale connection check を設定した AsyncEngine.
    """
    url = database_url.replace("postgres://", "postgresql+asyncpg://", 1).replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
    return create_async_engine(url, pool_pre_ping=True)
