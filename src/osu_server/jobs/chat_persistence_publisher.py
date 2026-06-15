"""Taskiq-backed transitional chat persistence work publisher."""

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
    async def kiq(self, *args: object, **kwargs: object) -> object:
        """Enqueue the task with primitive payload arguments."""
        ...


class _TaskBroker(Protocol):
    def find_task(self, task_name: str) -> _EnqueueableTask | None:
        """Find a registered task by stable task name."""
        ...


@final
class TaskiqChatPersistenceWorkPublisher(ChatPersistenceWorkPublisher):
    """Maps chat persistence work to the existing taskiq tasks."""

    _broker: _TaskBroker

    def __init__(self, broker: _TaskBroker) -> None:
        self._broker = broker

    @override
    async def publish_channel_message(
        self,
        work: ChannelMessagePersistenceWork,
    ) -> None:
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
        return self._broker.find_task(task_name)
