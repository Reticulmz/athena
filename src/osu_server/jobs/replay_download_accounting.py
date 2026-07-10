"""Taskiq adapters for replay download accounting."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Protocol, cast, final

import structlog
from taskiq import Context, TaskiqDepends

from osu_server.infrastructure.jobs.registry import jobs
from osu_server.services.commands.scores import (
    ReplayDownloadAccountingInput,
    ReplayDownloadAccountingResult,
)

if TYPE_CHECKING:
    from taskiq import TaskiqState

_ACCOUNT_REPLAY_DOWNLOAD_TASK_NAME = "account_replay_download"
logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))


class ReplayDownloadAccountingExecutor(Protocol):
    """Replay download accounting job が要求する use-case surface."""

    async def execute(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> ReplayDownloadAccountingResult:
        """Replay download accounting command を実行する.

        Args:
            input_data: replay download 成功後の accounting 入力。

        Returns:
            Replay View Count と latest activity branch の結果。

        Raises:
            実装依存。job adapter は runtime state 不足以外を use-case に委譲する。

        Constraints:
            taskiq adapter は repository や concrete state backend を直接扱わない。
        """
        ...


class _EnqueueableTask(Protocol):
    """Taskiq task enqueue に必要な最小 surface."""

    async def kiq(self, *args: object, **kwargs: object) -> object:
        """Taskiq job を primitive payload で enqueue する.

        Args:
            args: task に渡す positional payload。
            kwargs: task に渡す keyword payload。

        Returns:
            broker 実装依存の enqueue 結果。

        Raises:
            broker 実装依存の enqueue 例外。
        """
        ...


class _TaskBroker(Protocol):
    """Taskiq task lookup に必要な最小 surface."""

    def find_task(self, task_name: str) -> _EnqueueableTask | None:
        """登録済み task を stable task name で探す.

        Args:
            task_name: taskiq に登録された task name。

        Returns:
            対応する task。未登録の場合は None。

        Raises:
            なし。
        """
        ...


@final
class TaskiqReplayDownloadAccountingPublisher:
    """Replay download accounting work を taskiq job として発行する."""

    _broker: _TaskBroker

    def __init__(self, broker: _TaskBroker) -> None:
        """Taskiq broker を受け取る.

        Args:
            broker: task lookup と enqueue を行う taskiq broker。

        Returns:
            None。

        Raises:
            なし。
        """
        self._broker = broker

    async def publish(self, input_data: ReplayDownloadAccountingInput) -> None:
        """Replay download accounting job を best-effort に enqueue する.

        Args:
            input_data: replay download 成功後の accounting 入力。

        Returns:
            None。

        Raises:
            なし。task 未登録や enqueue 失敗はログに畳み込む。

        Constraints:
            response path では durable accounting を実行せず、primitive payload だけを渡す。
        """
        task = self._broker.find_task(_ACCOUNT_REPLAY_DOWNLOAD_TASK_NAME)
        if task is None:
            logger.error(
                "replay_download_accounting_task_not_registered",
                task_name=_ACCOUNT_REPLAY_DOWNLOAD_TASK_NAME,
                score_id=input_data.score_id,
                viewer_user_id=input_data.viewer_user_id,
                score_owner_user_id=input_data.score_owner_user_id,
            )
            return

        try:
            _ = await task.kiq(
                input_data.score_id,
                input_data.score_owner_user_id,
                input_data.viewer_user_id,
                input_data.occurred_at.isoformat(),
            )
        except Exception:
            logger.exception(
                "replay_download_accounting_enqueue_failed",
                task_name=_ACCOUNT_REPLAY_DOWNLOAD_TASK_NAME,
                score_id=input_data.score_id,
                viewer_user_id=input_data.viewer_user_id,
                score_owner_user_id=input_data.score_owner_user_id,
            )


def get_replay_download_accounting_executor(
    state: TaskiqState,
) -> ReplayDownloadAccountingExecutor | None:
    """Taskiq state から replay download accounting use-case を返す.

    Args:
        state: taskiq worker runtime state。

    Returns:
        登録済み use-case。未登録の場合は None。

    Raises:
        なし。
    """
    return cast(
        "ReplayDownloadAccountingExecutor | None",
        getattr(state, "replay_download_accounting_executor", None),
    )


@jobs.register(task_name=_ACCOUNT_REPLAY_DOWNLOAD_TASK_NAME)
async def account_replay_download(
    score_id: int,
    score_owner_user_id: int,
    viewer_user_id: int,
    occurred_at_iso: str,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Replay download accounting job を command use-case に委譲する.

    Args:
        score_id: replay download 対象 score id。
        score_owner_user_id: 対象 score の owner user id。
        viewer_user_id: 認証済み viewer user id。
        occurred_at_iso: replay download 成功時刻の ISO 8601 文字列。
        context: taskiq runtime context。

    Returns:
        None。

    Raises:
        RuntimeError: worker runtime state に use-case が登録されていない場合。
        ValueError: occurred_at_iso が不正、または input precondition に違反する場合。
    """
    use_case = get_replay_download_accounting_executor(context.state)
    if use_case is None:
        logger.error(
            "replay_download_accounting_runtime_unavailable",
            task_name=_ACCOUNT_REPLAY_DOWNLOAD_TASK_NAME,
            score_id=score_id,
            viewer_user_id=viewer_user_id,
            score_owner_user_id=score_owner_user_id,
        )
        msg = "replay download accounting use-case is not registered"
        raise RuntimeError(msg)

    occurred_at = _parse_occurred_at(occurred_at_iso)
    _ = await use_case.execute(
        ReplayDownloadAccountingInput(
            score_id=score_id,
            score_owner_user_id=score_owner_user_id,
            viewer_user_id=viewer_user_id,
            occurred_at=occurred_at,
        )
    )


def _parse_occurred_at(occurred_at_iso: str) -> datetime:
    """ISO 8601 payload を datetime に変換する.

    Args:
        occurred_at_iso: replay download 成功時刻の ISO 8601 文字列。

    Returns:
        datetime.fromisoformat() で復元した datetime。

    Raises:
        ValueError: occurred_at_iso が datetime として parse できない場合。
    """
    try:
        return datetime.fromisoformat(occurred_at_iso)
    except ValueError:
        logger.exception(
            "replay_download_accounting_payload_invalid",
            task_name=_ACCOUNT_REPLAY_DOWNLOAD_TASK_NAME,
            field="occurred_at_iso",
        )
        raise


__all__ = [
    "ReplayDownloadAccountingExecutor",
    "TaskiqReplayDownloadAccountingPublisher",
    "account_replay_download",
    "get_replay_download_accounting_executor",
]
