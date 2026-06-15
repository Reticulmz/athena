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

from osu_server.composition.providers.container import make_worker_container
from osu_server.composition.taskiq_integration import (
    WorkerRuntimeProviderSet,
    WorkerRuntimeUseCases,
    setup_taskiq_dishka,
)
from osu_server.composition.worker_runtime import (
    create_worker_beatmap_file_fetch,
    create_worker_beatmap_metadata_fetch,
    create_worker_chat_persistence_use_cases,
)
from osu_server.config import load_config
from osu_server.infrastructure.cache.valkey_client import create_valkey_client
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.infrastructure.logging import setup_logging
from osu_server.jobs import register_all_jobs
from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
)
from osu_server.services.commands.chat import (
    PersistChannelMessageUseCase,
    PersistPrivateMessageUseCase,
)

if TYPE_CHECKING:
    from dishka import AsyncContainer
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


def _get_dishka_container(state: TaskiqState) -> AsyncContainer | None:
    """Return the Dishka worker container stored in taskiq state."""
    return cast("AsyncContainer | None", getattr(state, "dishka_container", None))


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

    (
        persist_channel_message_use_case,
        persist_private_message_use_case,
    ) = create_worker_chat_persistence_use_cases(
        session_factory=session_factory,
    )
    beatmap_metadata_fetch = create_worker_beatmap_metadata_fetch(
        session_factory=session_factory,
        config=_config,
    )
    beatmap_file_fetch = await create_worker_beatmap_file_fetch(
        session_factory=session_factory,
        config=_config,
    )
    worker_container = make_worker_container(
        _config,
        overrides=(
            WorkerRuntimeProviderSet(
                WorkerRuntimeUseCases(
                    persist_channel_message=persist_channel_message_use_case,
                    persist_private_message=persist_private_message_use_case,
                    fetch_beatmap_metadata=beatmap_metadata_fetch,
                    fetch_beatmap_file=beatmap_file_fetch,
                )
            ),
        ),
    )
    setup_taskiq_dishka(worker_container, broker)

    state.dishka_container = worker_container
    state.persist_channel_message_use_case = await worker_container.get(
        PersistChannelMessageUseCase
    )
    state.persist_private_message_use_case = await worker_container.get(
        PersistPrivateMessageUseCase
    )
    state.beatmap_metadata_fetch = await worker_container.get(FetchBeatmapMetadataUseCase)
    state.beatmap_file_fetch = await worker_container.get(FetchBeatmapFileUseCase)

    logger.info("worker_started")


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state: TaskiqState) -> None:
    """Dispose of worker runtime state created during startup."""
    engine = _get_engine(state)
    valkey = _get_valkey(state)
    dishka_container = _get_dishka_container(state)

    state.engine = None
    state.session_factory = None
    state.valkey = None
    state.dishka_container = None
    state.persist_channel_message_use_case = None
    state.persist_private_message_use_case = None
    state.beatmap_metadata_fetch = None
    state.beatmap_file_fetch = None

    if engine is not None:
        await engine.dispose()
    if valkey is not None:
        await valkey.close()
    if dishka_container is not None:
        await dishka_container.close()

    logger.info("worker_stopped")
