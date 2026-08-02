"""chat persistence work を既存の Taskiq task へ発行する adapter を定義する."""

from __future__ import annotations

from typing import Protocol, final, override

import structlog

from osu_server.services.commands.chat.persistence_work import (
    ChannelMessagePersistenceWork,
    ChatPersistenceWorkPublisher,
    PrivateMessagePersistenceWork,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


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
class TaskiqChatPersistenceWorkPublisher(ChatPersistenceWorkPublisher):
    """chat persistence work を既存の Taskiq task へ発行する.

    Attributes:
        _broker (_TaskBroker): task の検索と enqueue を担う broker.

    Notes:
        task 未登録または enqueue 失敗はログに記録して caller へ送出しない.
    """

    _broker: _TaskBroker

    def __init__(self, broker: _TaskBroker) -> None:
        """Taskiq broker を work publisher に設定する.

        Args:
            broker (_TaskBroker): task の検索と enqueue を担う broker.
        """
        self._broker = broker

    @override
    async def publish_channel_message(
        self,
        work: ChannelMessagePersistenceWork,
    ) -> None:
        """Channel message persistence work を best effort で enqueue する.

        Args:
            work (ChannelMessagePersistenceWork): sender と channel と本文を持つ accepted work.

        Returns:
            None: task を enqueue するか失敗をログに記録して完了する.

        Notes:
            `persist_channel_message` task が未登録または enqueue 失敗なら例外を送出しない.
        """
        task = self._find_task("persist_channel_message")
        if task is None:
            logger.error(
                "chat_persistence_task_not_registered",
                task_name="persist_channel_message",
                sender_id=work.sender_id,
                channel_name=work.channel_name,
            )
            return

        try:
            _ = await task.kiq(
                work.sender_id,
                work.channel_name,
                work.sender_name,
                work.content,
            )
        except Exception:
            logger.exception(
                "chat_persistence_enqueue_failed",
                task_name="persist_channel_message",
                sender_id=work.sender_id,
                channel_name=work.channel_name,
            )

    @override
    async def publish_private_message(
        self,
        work: PrivateMessagePersistenceWork,
    ) -> None:
        """Private message persistence work を best effort で enqueue する.

        Args:
            work (PrivateMessagePersistenceWork): sender と recipient と本文を持つ accepted work.

        Returns:
            None: task を enqueue するか失敗をログに記録して完了する.

        Notes:
            `persist_private_message` task が未登録または enqueue 失敗なら例外を送出しない.
        """
        task = self._find_task("persist_private_message")
        if task is None:
            logger.error(
                "chat_persistence_task_not_registered",
                task_name="persist_private_message",
                sender_id=work.sender_id,
                target_id=work.target_id,
            )
            return

        try:
            _ = await task.kiq(
                work.sender_id,
                work.target_id,
                work.sender_name,
                work.target_name,
                work.content,
            )
        except Exception:
            logger.exception(
                "chat_persistence_enqueue_failed",
                task_name="persist_private_message",
                sender_id=work.sender_id,
                target_id=work.target_id,
            )

    def _find_task(self, task_name: str) -> _EnqueueableTask | None:
        """Stable task name に対応する Taskiq task を返す.

        Args:
            task_name (str): Taskiq registry に登録された stable task 名.

        Returns:
            _EnqueueableTask | None: 対応する task または未登録時の None.
        """
        return self._broker.find_task(task_name)
