"""Taskiq worker entry point.

Runs as a separate process to execute background jobs (e.g. message
persistence).  The ``startup`` hook initialises a SQLAlchemy async engine
and session factory; ``shutdown`` disposes the engine.

Start with: ``taskiq worker osu_server.worker:broker``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from taskiq_redis import ListQueueBroker

from osu_server.config import load_config

if TYPE_CHECKING:
    from taskiq import TaskiqState

from taskiq import TaskiqEvents

from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_config = load_config()

broker = ListQueueBroker(url=str(_config.valkey_url))


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState) -> None:
    """Initialise DB engine and session factory, storing them in *state*."""
    engine: AsyncEngine = create_engine(str(_config.database_url))
    session_factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)

    state.engine = engine
    state.session_factory = session_factory

    logger.info("worker_started")


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state: TaskiqState) -> None:
    """Dispose of the DB engine created during startup."""
    engine = getattr(state, "engine", None)
    if isinstance(engine, AsyncEngine):
        await engine.dispose()

    logger.info("worker_stopped")
