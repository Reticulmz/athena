"""Taskiq worker entry point.

Runs as a separate process to execute background jobs. The ``startup`` hook
initialises a SQLAlchemy async engine and session factory; ``shutdown``
disposes the engine.

Start with: ``taskiq worker osu_server.worker:broker``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import structlog
from taskiq import TaskiqEvents
from taskiq_redis import ListQueueBroker

from osu_server.config import load_config
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.infrastructure.logging import setup_logging
from osu_server.jobs import register_all_jobs

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine
    from taskiq import TaskiqState

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_config = load_config()

broker = ListQueueBroker(url=str(_config.valkey_url))
register_all_jobs(broker)


def _get_engine(state: TaskiqState) -> AsyncEngine | None:
    """Return the SQLAlchemy engine stored in taskiq state."""
    return cast("AsyncEngine | None", getattr(state, "engine", None))


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState) -> None:
    """Initialise DB engine and session factory."""
    setup_logging(_config)
    engine = create_engine(str(_config.database_url))

    state.engine = engine
    state.session_factory = create_session_factory(engine)

    logger.info("worker_started")


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state: TaskiqState) -> None:
    """Dispose of the DB engine created during startup."""
    engine = _get_engine(state)

    state.engine = None
    state.session_factory = None

    if engine is not None:
        await engine.dispose()

    logger.info("worker_stopped")
