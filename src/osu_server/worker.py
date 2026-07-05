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
    setup_taskiq_dishka,
    setup_taskiq_query_diagnostics,
)
from osu_server.config import load_config
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
from osu_server.services.commands.scores.leaderboards import (
    RebuildBeatmapLeaderboardsForBeatmapsetUseCase,
    RebuildBeatmapLeaderboardsForUserUseCase,
)
from osu_server.services.commands.scores.performance import (
    ExecutePerformanceCalculationUseCase,
    ProcessPerformanceRecalculationBatchUseCase,
)

if TYPE_CHECKING:
    from dishka import AsyncContainer
    from taskiq import TaskiqState

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_config = load_config()

broker = ListQueueBroker(url=str(_config.valkey_url))
register_all_jobs(broker)


def _get_dishka_container(state: TaskiqState) -> AsyncContainer | None:
    """Return the Dishka worker container stored in taskiq state."""
    return cast("AsyncContainer | None", getattr(state, "dishka_container", None))


def _clear_worker_runtime_state(state: TaskiqState) -> None:
    state.dishka_container = None
    state.persist_channel_message_use_case = None
    state.persist_private_message_use_case = None
    state.beatmap_metadata_fetch = None
    state.beatmap_file_fetch = None
    state.score_performance_calculation_executor = None
    state.performance_recalculation_batch_processor = None
    state.beatmap_leaderboard_user_rebuild_use_case = None
    state.beatmap_leaderboard_beatmapset_rebuild_use_case = None


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState) -> None:
    """Initialise worker runtime state for task execution."""
    setup_logging(_config)
    worker_container: AsyncContainer | None = None

    try:
        worker_container = make_worker_container(_config)
        setup_taskiq_dishka(worker_container, broker)
        setup_taskiq_query_diagnostics(_config, broker)

        state.dishka_container = worker_container
        state.persist_channel_message_use_case = await worker_container.get(
            PersistChannelMessageUseCase
        )
        state.persist_private_message_use_case = await worker_container.get(
            PersistPrivateMessageUseCase
        )
        state.beatmap_metadata_fetch = await worker_container.get(FetchBeatmapMetadataUseCase)
        state.beatmap_file_fetch = await worker_container.get(FetchBeatmapFileUseCase)
        state.score_performance_calculation_executor = await worker_container.get(
            ExecutePerformanceCalculationUseCase
        )
        state.performance_recalculation_batch_processor = await worker_container.get(
            ProcessPerformanceRecalculationBatchUseCase
        )
        state.beatmap_leaderboard_user_rebuild_use_case = await worker_container.get(
            RebuildBeatmapLeaderboardsForUserUseCase
        )
        state.beatmap_leaderboard_beatmapset_rebuild_use_case = await worker_container.get(
            RebuildBeatmapLeaderboardsForBeatmapsetUseCase
        )
    except Exception:
        _clear_worker_runtime_state(state)
        if worker_container is not None:
            await worker_container.close()
        raise

    logger.info("worker_started")


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state: TaskiqState) -> None:
    """Dispose of worker runtime state created during startup."""
    dishka_container = _get_dishka_container(state)

    _clear_worker_runtime_state(state)

    if dishka_container is not None:
        await dishka_container.close()

    logger.info("worker_stopped")
