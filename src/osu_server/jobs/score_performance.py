"""Taskiq adapters for score performance command use-cases."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Protocol, cast, final

import structlog
from taskiq import Context, TaskiqDepends

from osu_server.infrastructure.jobs.registry import jobs
from osu_server.services.commands.scores.performance import (
    ExecutePerformanceCalculationCommand,
    ExecutePerformanceCalculationResult,
)

if TYPE_CHECKING:
    from taskiq import TaskiqState

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class ScorePerformanceCalculationExecutor(Protocol):
    """Calculation use-case surface required by job adapters."""

    async def execute(
        self,
        command: ExecutePerformanceCalculationCommand,
    ) -> ExecutePerformanceCalculationResult: ...


class PerformanceRecalculationBatchProcessor(Protocol):
    """Recalculation batch use-case surface required by job adapters."""

    async def execute(self, batch_id: int) -> object: ...


class _EnqueueableTask(Protocol):
    async def kiq(self, *args: object, **kwargs: object) -> object:
        """Enqueue the task with primitive payload arguments."""
        ...


class _TaskBroker(Protocol):
    def find_task(self, task_name: str) -> _EnqueueableTask | None:
        """Find a registered task by stable task name."""
        ...


@final
class TaskiqPerformanceCalculationWorkerWake:
    """Maps performance calculation wake requests to taskiq jobs."""

    def __init__(self, broker: _TaskBroker) -> None:
        self._broker = broker

    async def wake_score_calculation(self, *, score_id: int, calculation_id: int) -> None:
        task_name = "calculate_score_performance"
        task = self._broker.find_task(task_name)
        if task is None:
            logger.error(
                "score_performance_calculation_task_not_registered",
                task_name=task_name,
                score_id=score_id,
                calculation_id=calculation_id,
            )
            msg = "score performance calculation task is not registered"
            raise RuntimeError(msg)

        try:
            _ = await task.kiq(score_id, calculation_id)
        except Exception:
            logger.exception(
                "score_performance_calculation_enqueue_failed",
                task_name=task_name,
                score_id=score_id,
                calculation_id=calculation_id,
            )
            raise


def get_score_performance_calculation_executor(
    state: TaskiqState,
) -> ScorePerformanceCalculationExecutor | None:
    """Return the score performance calculation use-case from taskiq state."""
    return cast(
        "ScorePerformanceCalculationExecutor | None",
        getattr(state, "score_performance_calculation_executor", None),
    )


def get_performance_recalculation_batch_processor(
    state: TaskiqState,
) -> PerformanceRecalculationBatchProcessor | None:
    """Return the performance recalculation batch use-case from taskiq state."""
    return cast(
        "PerformanceRecalculationBatchProcessor | None",
        getattr(state, "performance_recalculation_batch_processor", None),
    )


@jobs.register(task_name="calculate_score_performance")
async def calculate_score_performance(
    score_id: int,
    calculation_id: int,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Delegate one score performance calculation to the command use-case."""
    use_case = get_score_performance_calculation_executor(context.state)
    if use_case is None:
        logger.error(
            "score_performance_calculation_runtime_unavailable",
            task_name="calculate_score_performance",
            score_id=score_id,
            calculation_id=calculation_id,
        )
        msg = "score performance calculation use-case is not registered"
        raise RuntimeError(msg)

    _ = await use_case.execute(
        ExecutePerformanceCalculationCommand(
            calculation_id=calculation_id,
            claim_owner=_claim_owner_from_context(context),
            claimed_at=datetime.now(tz=UTC),
        )
    )


@jobs.register(task_name="process_performance_recalculation_batch")
async def process_performance_recalculation_batch(
    batch_id: int,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Delegate durable recalculation batch processing to the command use-case."""
    use_case = get_performance_recalculation_batch_processor(context.state)
    if use_case is None:
        logger.error(
            "performance_recalculation_batch_runtime_unavailable",
            task_name="process_performance_recalculation_batch",
            batch_id=batch_id,
        )
        msg = "performance recalculation batch use-case is not registered"
        raise RuntimeError(msg)

    _ = await use_case.execute(batch_id)


def _claim_owner_from_context(context: Context) -> str:
    return f"taskiq:{context.message.task_id}"


__all__ = [
    "PerformanceRecalculationBatchProcessor",
    "ScorePerformanceCalculationExecutor",
    "TaskiqPerformanceCalculationWorkerWake",
    "calculate_score_performance",
    "get_performance_recalculation_batch_processor",
    "get_score_performance_calculation_executor",
    "process_performance_recalculation_batch",
]
