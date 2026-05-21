"""SQLAlchemy async session factory.

Provides a factory function that creates an ``async_sessionmaker`` bound to
a given ``AsyncEngine``.
"""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to *engine*.

    Args:
        engine: The SQLAlchemy async engine to bind sessions to.

    Returns:
        An ``async_sessionmaker`` that produces ``AsyncSession`` instances.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
