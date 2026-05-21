"""SQLAlchemy async engine factory.

Creates an AsyncEngine with connection pooling for PostgreSQL via asyncpg.
"""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine from a database URL.

    Converts ``postgresql://`` scheme to ``postgresql+asyncpg://`` if needed,
    so callers can pass the standard DATABASE_URL without worrying about the
    driver suffix.

    Args:
        database_url: PostgreSQL connection URL.

    Returns:
        An AsyncEngine configured with asyncpg driver.
    """
    url = database_url.replace("postgres://", "postgresql+asyncpg://", 1).replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
    return create_async_engine(url)
