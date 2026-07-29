"""score performance command use-case を呼び出す Taskiq adapter を定義する."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Protocol, cast, final

import structlog
from taskiq import Context, TaskiqDepends

from osu_server.infrastructure.jobs.registry import jobs
from osu_server.services.commands.scores.performance import (
    ExecutePerformanceCalculationCommand,
    ExecutePerformanceCalculationResult,
    ProcessPerformanceRecalculationBatchCommand,
    ProcessPerformanceRecalculationBatchResult,
)

if TYPE_CHECKING:
    from taskiq import TaskiqState

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class ScorePerformanceCalculationExecutor(Protocol):
    """score performance calculation job が要求する use-case 境界を表す."""

    async def execute(
        self,
        command: ExecutePerformanceCalculationCommand,
    ) -> ExecutePerformanceCalculationResult:
        """Score performance calculation command を実行する.

        Args:
            command (ExecutePerformanceCalculationCommand): claim 情報を持つ calculation command.

        Returns:
            ExecutePerformanceCalculationResult: calculation 実行の結果.
        """
        ...


class PerformanceRecalculationBatchProcessor(Protocol):
    """performance recalculation batch job が要求する use-case 境界を表す."""

    async def execute(
        self,
        command: ProcessPerformanceRecalculationBatchCommand,
    ) -> ProcessPerformanceRecalculationBatchResult:
        """Performance recalculation batch command を実行する.

        Args:
            command (ProcessPerformanceRecalculationBatchCommand): claim 情報を持つ batch command.

        Returns:
            ProcessPerformanceRecalculationBatchResult: batch 処理の結果.
        """
        ...


class _EnqueueableTask(Protocol):
    """primitive payload を enqueue できる Taskiq task の最小境界を表す."""

    async def kiq(self, *args: object, **kwargs: object) -> object:
        """Primitive payload 引数を持つ task を enqueue する.

        Args:
            *args (object): task に渡す positional payload.
            **kwargs (object): task に渡す keyword payload.

        Returns:
            object: broker 実装が返す enqueue 結果.
        """
        ...


class _TaskBroker(Protocol):
    """stable task name から Taskiq task を検索する最小境界を表す."""

    def find_task(self, task_name: str) -> _EnqueueableTask | None:
        """Stable task name で登録済み task を検索する.

        Args:
            task_name (str): Taskiq registry に登録された stable task 名.

        Returns:
            _EnqueueableTask | None: 対応する task または未登録時の None.
        """
        ...


@final
class TaskiqPerformanceCalculationWorkerWake:
    """performance calculation の起動要求を Taskiq job へ変換する.

    Attributes:
        _broker (_TaskBroker): task の検索と enqueue を担う broker.
    """

    def __init__(self, broker: _TaskBroker) -> None:
        """Taskiq broker を calculation wake adapter に設定する.

        Args:
            broker (_TaskBroker): task の検索と enqueue を担う broker.
        """
        self._broker = broker

    async def wake_score_calculation(self, *, score_id: int, calculation_id: int) -> None:
        """Score performance calculation task を enqueue する.

        Args:
            score_id (int): 計算対象 score の ID.
            calculation_id (int): durable calculation request の ID.

        Returns:
            None: `calculate_score_performance` task の enqueue を完了する.

        Raises:
            RuntimeError: 対応する task が broker に未登録の場合.
        """
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


@final
class TaskiqPerformanceRecalculationBatchWorkerWake:
    """performance recalculation batch の起動要求を Taskiq job へ変換する.

    Attributes:
        _broker (_TaskBroker): task の検索と enqueue を担う broker.
    """

    def __init__(self, broker: _TaskBroker) -> None:
        """Taskiq broker を recalculation batch wake adapter に設定する.

        Args:
            broker (_TaskBroker): task の検索と enqueue を担う broker.
        """
        self._broker = broker

    async def wake_recalculation_batch(self, *, batch_id: int) -> None:
        """Performance recalculation batch task を enqueue する.

        Args:
            batch_id (int): 処理する durable recalculation batch の ID.

        Returns:
            None: `process_performance_recalculation_batch` task の enqueue を完了する.

        Raises:
            RuntimeError: 対応する task が broker に未登録の場合.
        """
        task_name = "process_performance_recalculation_batch"
        task = self._broker.find_task(task_name)
        if task is None:
            logger.error(
                "performance_recalculation_batch_task_not_registered",
                task_name=task_name,
                batch_id=batch_id,
            )
            msg = "performance recalculation batch task is not registered"
            raise RuntimeError(msg)

        try:
            _ = await task.kiq(batch_id)
        except Exception:
            logger.exception(
                "performance_recalculation_batch_enqueue_failed",
                task_name=task_name,
                batch_id=batch_id,
            )
            raise


def get_score_performance_calculation_executor(
    state: TaskiqState,
) -> ScorePerformanceCalculationExecutor | None:
    """Taskiq state から score performance calculation use-case を返す.

    Args:
        state (TaskiqState): worker runtime が保持する Taskiq state.

    Returns:
        ScorePerformanceCalculationExecutor | None: 登録済み use-case または未登録時の None.
    """
    return cast(
        "ScorePerformanceCalculationExecutor | None",
        getattr(state, "score_performance_calculation_executor", None),
    )


def get_performance_recalculation_batch_processor(
    state: TaskiqState,
) -> PerformanceRecalculationBatchProcessor | None:
    """Taskiq state から performance recalculation batch processor を返す.

    Args:
        state (TaskiqState): worker runtime が保持する Taskiq state.

    Returns:
        PerformanceRecalculationBatchProcessor | None: 登録済み processor または未登録時の None.
    """
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
    """Score performance calculation を command use-case に委譲する.

    Args:
        score_id (int): 運用ログに記録する calculation 対象 score の ID.
        calculation_id (int): durable calculation request の ID.
        context (Context): use-case と task ID を取得する Taskiq runtime context.

    Returns:
        None: `calculate_score_performance` task を use-case へ委譲して完了する.

    Raises:
        RuntimeError: score performance calculation use-case が worker state に未登録の場合.

    Notes:
        claim owner は context の task ID から導出し 現在時刻を UTC で記録する.
    """
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
    """Durable performance recalculation batch 処理を command use-case に委譲する.

    Args:
        batch_id (int): 処理する durable recalculation batch の ID.
        context (Context): use-case と task ID と broker を取得する Taskiq runtime context.

    Returns:
        None: batch を処理し未処理 item が残る場合は同じ task を再起動する.

    Raises:
        RuntimeError: recalculation batch processor が worker state に未登録の場合.

    Notes:
        claim owner は context の task ID から導出し claimed_count が正なら再 enqueue する.
    """
    use_case = get_performance_recalculation_batch_processor(context.state)
    if use_case is None:
        logger.error(
            "performance_recalculation_batch_runtime_unavailable",
            task_name="process_performance_recalculation_batch",
            batch_id=batch_id,
        )
        msg = "performance recalculation batch use-case is not registered"
        raise RuntimeError(msg)

    result = await use_case.execute(
        ProcessPerformanceRecalculationBatchCommand(
            batch_id=batch_id,
            claim_owner=_claim_owner_from_context(context),
            claimed_at=datetime.now(tz=UTC),
        )
    )
    if result.claimed_count > 0:
        wake = TaskiqPerformanceRecalculationBatchWorkerWake(cast("_TaskBroker", context.broker))
        await wake.wake_recalculation_batch(batch_id=batch_id)


def _claim_owner_from_context(context: Context) -> str:
    """Taskiq context の task ID から claim owner を作る.

    Args:
        context (Context): task ID を保持する Taskiq runtime context.

    Returns:
        str: `taskiq:` prefix と task ID を結合した claim owner.
    """
    return f"taskiq:{context.message.task_id}"


__all__ = [
    "PerformanceRecalculationBatchProcessor",
    "ScorePerformanceCalculationExecutor",
    "TaskiqPerformanceCalculationWorkerWake",
    "TaskiqPerformanceRecalculationBatchWorkerWake",
    "calculate_score_performance",
    "get_performance_recalculation_batch_processor",
    "get_score_performance_calculation_executor",
    "process_performance_recalculation_batch",
]
