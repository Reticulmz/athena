"""SQLAlchemy async session factoryを作成するmodule.

指定した``AsyncEngine``へboundした``async_sessionmaker``を提供する.
"""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """指定したengineへboundしたasync session factoryを作成する.

    Args:
        engine (AsyncEngine): sessionをbindするSQLAlchemy async engine.

    Returns:
        async_sessionmaker[AsyncSession]: ``AsyncSession``を生成するfactory.

    Notes:
        command serviceがcommit後もdomain objectを読めるよう
        ``expire_on_commit``はFalseに固定する.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
