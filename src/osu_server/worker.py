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

from osu_server.composition.worker_runtime import (
    create_worker_beatmap_file_fetch,
    create_worker_beatmap_metadata_fetch,
    create_worker_chat_service,
)
from osu_server.config import load_config
from osu_server.infrastructure.cache.valkey_client import create_valkey_client
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.infrastructure.logging import setup_logging
from osu_server.jobs import register_all_jobs

if TYPE_CHECKING:
    from glide import GlideClient
    from sqlalchemy.ext.asyncio import AsyncEngine
    from taskiq import TaskiqState

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_config = load_config()

broker = ListQueueBroker(url=str(_config.valkey_url))
register_all_jobs(broker)


def _get_engine(state: TaskiqState) -> AsyncEngine | None:
    """Return the SQLAlchemy engine stored in taskiq state."""
    return cast("AsyncEngine | None", getattr(state, "engine", None))


def _get_valkey(state: TaskiqState) -> GlideClient | None:
    """Return the Valkey client stored in taskiq state."""
    return cast("GlideClient | None", getattr(state, "valkey", None))


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState) -> None:
    """Initialise worker runtime state for task execution."""
    setup_logging(_config)
    engine = create_engine(str(_config.database_url))
    session_factory = create_session_factory(engine)
    valkey = await create_valkey_client(str(_config.valkey_url))

    state.engine = engine
    state.session_factory = session_factory
    state.valkey = valkey
    state.chat_service = create_worker_chat_service(
        session_factory=session_factory,
        valkey=valkey,
        config=_config,
    )
    state.beatmap_metadata_fetch = create_worker_beatmap_metadata_fetch(
        session_factory=session_factory,
        config=_config,
    )
    state.beatmap_file_fetch = await create_worker_beatmap_file_fetch(
        session_factory=session_factory,
        config=_config,
    )

    logger.info("worker_started")


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state: TaskiqState) -> None:
    """Dispose of worker runtime state created during startup."""
    engine = _get_engine(state)
    valkey = _get_valkey(state)

    state.engine = None
    state.session_factory = None
    state.valkey = None
    state.chat_service = None
    state.beatmap_metadata_fetch = None
    state.beatmap_file_fetch = None

    if engine is not None:
        await engine.dispose()
    if valkey is not None:
        await valkey.close()

    logger.info("worker_stopped")
