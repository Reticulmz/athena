"""Taskiq adapters for Beatmap Leaderboard rebuild command use-cases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol, cast, final

import structlog
from taskiq import Context, TaskiqDepends

from osu_server.infrastructure.jobs.registry import jobs
from osu_server.services.commands.scores.leaderboards import (
    RebuildBeatmapLeaderboardsForBeatmapsetCommand,
    RebuildBeatmapLeaderboardsForUserCommand,
    RebuildBeatmapLeaderboardsResult,
)

if TYPE_CHECKING:
    from taskiq import TaskiqState

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))

REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK = "rebuild_beatmap_leaderboards_for_user"
REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK = "rebuild_beatmap_leaderboards_for_beatmapset"


class BeatmapLeaderboardUserRebuildUseCase(Protocol):
    """User-slice rebuild use-case surface required by job adapters."""

    async def execute(
        self,
        command: RebuildBeatmapLeaderboardsForUserCommand,
    ) -> RebuildBeatmapLeaderboardsResult: ...


class BeatmapLeaderboardBeatmapsetRebuildUseCase(Protocol):
    """Beatmapset-slice rebuild use-case surface required by job adapters."""

    async def execute(
        self,
        command: RebuildBeatmapLeaderboardsForBeatmapsetCommand,
    ) -> RebuildBeatmapLeaderboardsResult: ...


class _EnqueueableTask(Protocol):
    async def kiq(self, *args: object, **kwargs: object) -> object:
        """Enqueue the task with primitive payload arguments."""
        ...


class _TaskBroker(Protocol):
    def find_task(self, task_name: str) -> _EnqueueableTask | None:
        """Find a registered task by stable task name."""
        ...


@final
class TaskiqBeatmapLeaderboardRebuildWorkerWake:
    """Maps leaderboard rebuild wake requests to taskiq jobs."""

    def __init__(self, broker: _TaskBroker) -> None:
        self._broker = broker

    async def wake_user_rebuild(self, *, user_id: int, reason: str) -> None:
        task_name = REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK
        task = self._broker.find_task(task_name)
        if task is None:
            logger.error(
                "beatmap_leaderboard_rebuild_task_not_registered",
                task_name=task_name,
                target_kind="user",
                user_id=user_id,
                reason=reason,
            )
            msg = "Beatmap Leaderboard user rebuild task is not registered"
            raise RuntimeError(msg)

        try:
            _ = await task.kiq(user_id, reason)
        except Exception:
            logger.exception(
                "beatmap_leaderboard_rebuild_enqueue_failed",
                task_name=task_name,
                target_kind="user",
                user_id=user_id,
                reason=reason,
            )
            raise

    async def wake_beatmapset_rebuild(self, *, beatmapset_id: int, reason: str) -> None:
        task_name = REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK
        task = self._broker.find_task(task_name)
        if task is None:
            logger.error(
                "beatmap_leaderboard_rebuild_task_not_registered",
                task_name=task_name,
                target_kind="beatmapset",
                beatmapset_id=beatmapset_id,
                reason=reason,
            )
            msg = "Beatmap Leaderboard beatmapset rebuild task is not registered"
            raise RuntimeError(msg)

        try:
            _ = await task.kiq(beatmapset_id, reason)
        except Exception:
            logger.exception(
                "beatmap_leaderboard_rebuild_enqueue_failed",
                task_name=task_name,
                target_kind="beatmapset",
                beatmapset_id=beatmapset_id,
                reason=reason,
            )
            raise


def get_beatmap_leaderboard_user_rebuild_use_case(
    state: TaskiqState,
) -> BeatmapLeaderboardUserRebuildUseCase | None:
    """Return the user rebuild use-case from taskiq state."""
    return cast(
        "BeatmapLeaderboardUserRebuildUseCase | None",
        getattr(state, "beatmap_leaderboard_user_rebuild_use_case", None),
    )


def get_beatmap_leaderboard_beatmapset_rebuild_use_case(
    state: TaskiqState,
) -> BeatmapLeaderboardBeatmapsetRebuildUseCase | None:
    """Return the beatmapset rebuild use-case from taskiq state."""
    return cast(
        "BeatmapLeaderboardBeatmapsetRebuildUseCase | None",
        getattr(state, "beatmap_leaderboard_beatmapset_rebuild_use_case", None),
    )


@jobs.register(task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK)
async def rebuild_beatmap_leaderboards_for_user(
    user_id: object,
    reason: object,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Delegate one user projection rebuild to the command use-case."""
    validated_user_id = _validate_positive_int(user_id, "user_id")
    validated_reason = _validate_non_empty_str(reason, "reason")
    use_case = get_beatmap_leaderboard_user_rebuild_use_case(context.state)
    if use_case is None:
        logger.error(
            "beatmap_leaderboard_rebuild_runtime_unavailable",
            task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK,
            target_kind="user",
            user_id=validated_user_id,
        )
        msg = "Beatmap Leaderboard user rebuild use-case is not registered"
        raise RuntimeError(msg)

    logger.info(
        "beatmap_leaderboard_rebuild_requested",
        task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK,
        target_kind="user",
        user_id=validated_user_id,
        reason=validated_reason,
    )
    result = await use_case.execute(
        RebuildBeatmapLeaderboardsForUserCommand(
            user_id=validated_user_id,
            reason=validated_reason,
        )
    )
    _log_completed(
        task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK,
        target_kind="user",
        reason=validated_reason,
        result=result,
        user_id=validated_user_id,
    )


@jobs.register(task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK)
async def rebuild_beatmap_leaderboards_for_beatmapset(
    beatmapset_id: object,
    reason: object,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Delegate one beatmapset projection rebuild to the command use-case."""
    validated_beatmapset_id = _validate_positive_int(beatmapset_id, "beatmapset_id")
    validated_reason = _validate_non_empty_str(reason, "reason")
    use_case = get_beatmap_leaderboard_beatmapset_rebuild_use_case(context.state)
    if use_case is None:
        logger.error(
            "beatmap_leaderboard_rebuild_runtime_unavailable",
            task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK,
            target_kind="beatmapset",
            beatmapset_id=validated_beatmapset_id,
        )
        msg = "Beatmap Leaderboard beatmapset rebuild use-case is not registered"
        raise RuntimeError(msg)

    logger.info(
        "beatmap_leaderboard_rebuild_requested",
        task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK,
        target_kind="beatmapset",
        beatmapset_id=validated_beatmapset_id,
        reason=validated_reason,
    )
    result = await use_case.execute(
        RebuildBeatmapLeaderboardsForBeatmapsetCommand(
            beatmapset_id=validated_beatmapset_id,
            reason=validated_reason,
        )
    )
    _log_completed(
        task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK,
        target_kind="beatmapset",
        reason=validated_reason,
        result=result,
        beatmapset_id=validated_beatmapset_id,
    )


def _validate_positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        msg = f"{field_name} must be a positive integer"
        raise ValueError(msg)
    return value


def _validate_non_empty_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        msg = f"{field_name} must be a non-empty string"
        raise ValueError(msg)
    return value


def _log_completed(
    *,
    task_name: str,
    target_kind: str,
    reason: str,
    result: RebuildBeatmapLeaderboardsResult,
    user_id: int | None = None,
    beatmapset_id: int | None = None,
) -> None:
    logger.info(
        "beatmap_leaderboard_rebuild_completed",
        task_name=task_name,
        target_kind=target_kind,
        user_id=user_id,
        beatmapset_id=beatmapset_id,
        reason=reason,
        target_found=result.target_found,
        source_score_count=result.source_score_count,
        projection_row_count=result.projection_row_count,
    )


__all__ = [
    "REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK",
    "REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK",
    "BeatmapLeaderboardBeatmapsetRebuildUseCase",
    "BeatmapLeaderboardUserRebuildUseCase",
    "TaskiqBeatmapLeaderboardRebuildWorkerWake",
    "get_beatmap_leaderboard_beatmapset_rebuild_use_case",
    "get_beatmap_leaderboard_user_rebuild_use_case",
    "rebuild_beatmap_leaderboards_for_beatmapset",
    "rebuild_beatmap_leaderboards_for_user",
]
