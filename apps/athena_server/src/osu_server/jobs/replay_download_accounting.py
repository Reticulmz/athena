"""replay download accounting command を呼び出す Taskiq adapter を定義する."""

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
    """replay download accounting job が要求する use-case 境界を表す."""

    async def execute(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> ReplayDownloadAccountingResult:
        """Replay download accounting command を実行する.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download 成功後の accounting 入力.

        Returns:
            ReplayDownloadAccountingResult: replay view count と latest activity branch の結果.

        Notes:
            job adapter は runtime state を解決して command を委譲するだけである.
        """
        ...


class _EnqueueableTask(Protocol):
    """Taskiq task enqueue に必要な最小境界を表す."""

    async def kiq(self, *args: object, **kwargs: object) -> object:
        """Taskiq job を primitive payload で enqueue する.

        Args:
            *args (object): task に渡す positional payload.
            **kwargs (object): task に渡す keyword payload.

        Returns:
            object: broker 実装が返す enqueue 結果.
        """
        ...


class _TaskBroker(Protocol):
    """Taskiq task lookup に必要な最小境界を表す."""

    def find_task(self, task_name: str) -> _EnqueueableTask | None:
        """登録済み task を stable task name で探す.

        Args:
            task_name (str): Taskiq registry に登録された stable task 名.

        Returns:
            _EnqueueableTask | None: 対応する task または未登録時の None.
        """
        ...


@final
class TaskiqReplayDownloadAccountingPublisher:
    """replay download accounting work を Taskiq job として発行する.

    Attributes:
        _broker (_TaskBroker): task の検索と enqueue を担う broker.

    Notes:
        task 未登録または enqueue 失敗は response path へ送出せず構造化ログへ記録する.
    """

    _broker: _TaskBroker

    def __init__(self, broker: _TaskBroker) -> None:
        """Taskiq broker を publisher に設定する.

        Args:
            broker (_TaskBroker): task の検索と enqueue を担う broker.
        """
        self._broker = broker

    async def publish(self, input_data: ReplayDownloadAccountingInput) -> None:
        """Replay download accounting job を best effort で enqueue する.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download 成功後の accounting 入力.

        Returns:
            None: primitive payload を enqueue するか失敗をログに記録して完了する.

        Notes:
            task 未登録または enqueue 失敗はログに記録し response path へ送出しない.
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
        state (TaskiqState): worker runtime が保持する Taskiq state.

    Returns:
        ReplayDownloadAccountingExecutor | None: 登録済み use-case または未登録時の None.
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
        score_id (int): replay download 対象 score の ID.
        score_owner_user_id (int): 対象 score の owner user ID.
        viewer_user_id (int): 認証済み viewer user ID.
        occurred_at_iso (str): replay download 成功時刻の ISO 8601 文字列.
        context (Context): use-case を取得する Taskiq runtime context.

    Returns:
        None: accounting input を作成して command use-case を実行する.

    Raises:
        RuntimeError: accounting use-case が worker state に未登録の場合.
        ValueError: occurred_at_iso が不正または input precondition に違反する場合.
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
        occurred_at_iso (str): replay download 成功時刻の ISO 8601 文字列.

    Returns:
        datetime: datetime.fromisoformat() で復元した datetime.

    Raises:
        ValueError: occurred_at_iso が datetime として parse できない場合.
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
