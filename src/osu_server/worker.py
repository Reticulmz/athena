# pyright: reportAny=false
"""ARQ worker entry point — ``arq osu_server.worker.WorkerSettings``.

Runs as a separate process to execute background jobs (e.g. message
persistence).  The ``startup`` hook initialises a SQLAlchemy async engine
and session factory; ``shutdown`` disposes the engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from collections.abc import Sequence

    from arq.typing import StartupShutdown
    from arq.worker import Function

from osu_server.config import load_config
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _redis_settings_from_url(redis_url: str) -> RedisSettings:
    """Build ARQ ``RedisSettings`` from a ``redis://`` DSN string."""
    return RedisSettings.from_dsn(redis_url)


async def startup(ctx: dict[str, object]) -> None:
    """Initialise DB engine and session factory, storing them in *ctx*."""
    config = load_config()
    engine: AsyncEngine = create_engine(str(config.database_url))
    session_factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)

    ctx["engine"] = engine
    ctx["session_factory"] = session_factory

    logger.info("worker_started")


async def shutdown(ctx: dict[str, object]) -> None:
    """Dispose of the DB engine created during startup."""
    engine = ctx.get("engine")
    if isinstance(engine, AsyncEngine):
        await engine.dispose()

    logger.info("worker_stopped")


_config: Final = load_config()


class WorkerSettings:
    """ARQ worker configuration — consumed by ``arq`` CLI."""

    functions: Sequence[Function] = []
    on_startup: StartupShutdown = startup
    on_shutdown: StartupShutdown = shutdown
    redis_settings: RedisSettings = _redis_settings_from_url(str(_config.redis_url))
