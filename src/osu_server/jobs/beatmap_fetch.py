"""Taskiq adapters for beatmap fetch command use-cases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol, cast

import structlog
from taskiq import Context, TaskiqDepends

from osu_server.domain.beatmaps import BeatmapFetchTarget
from osu_server.infrastructure.jobs.registry import jobs

if TYPE_CHECKING:
    from taskiq import TaskiqState

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class WorkerBeatmapMetadataFetch(Protocol):
    """Beatmap metadata fetch use-case surface required by job adapters."""

    async def execute(self, target: BeatmapFetchTarget) -> None: ...


class WorkerBeatmapFileFetch(Protocol):
    """Beatmap file fetch use-case surface required by job adapters."""

    async def execute(self, target: BeatmapFetchTarget) -> None: ...


def get_beatmap_metadata_fetch(state: TaskiqState) -> WorkerBeatmapMetadataFetch | None:
    """Return the beatmap metadata fetch use-case stored in taskiq state."""
    return cast(
        "WorkerBeatmapMetadataFetch | None",
        getattr(state, "beatmap_metadata_fetch", None),
    )


def get_beatmap_file_fetch(state: TaskiqState) -> WorkerBeatmapFileFetch | None:
    """Return the beatmap file fetch use-case stored in taskiq state."""
    return cast(
        "WorkerBeatmapFileFetch | None",
        getattr(state, "beatmap_file_fetch", None),
    )


@jobs.register(task_name="fetch_beatmap_metadata")
async def fetch_beatmap_metadata(
    target_type: str,
    target_key: str,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Taskiq adapter for the beatmap metadata fetch command."""
    use_case = get_beatmap_metadata_fetch(context.state)
    if use_case is None:
        logger.error(
            "beatmap_metadata_fetch_runtime_unavailable",
            task_name="fetch_beatmap_metadata",
            target_type=target_type,
            target_key=target_key,
        )
        msg = "beatmap metadata fetch use-case is not registered"
        raise RuntimeError(msg)
    target = BeatmapFetchTarget(target_type=target_type, target_key=target_key)
    await use_case.execute(target)


@jobs.register(task_name="fetch_beatmap_file")
async def fetch_beatmap_file(
    target_type: str,
    target_key: str,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Taskiq adapter for the beatmap file fetch command."""
    use_case = get_beatmap_file_fetch(context.state)
    if use_case is None:
        logger.error(
            "beatmap_file_fetch_runtime_unavailable",
            task_name="fetch_beatmap_file",
            target_type=target_type,
            target_key=target_key,
        )
        msg = "beatmap file fetch use-case is not registered"
        raise RuntimeError(msg)
    target = BeatmapFetchTarget(target_type=target_type, target_key=target_key)
    await use_case.execute(target)


__all__ = [
    "WorkerBeatmapFileFetch",
    "WorkerBeatmapMetadataFetch",
    "fetch_beatmap_file",
    "fetch_beatmap_metadata",
    "get_beatmap_file_fetch",
    "get_beatmap_metadata_fetch",
]
