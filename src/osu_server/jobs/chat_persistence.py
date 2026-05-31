"""Taskiq chat persistence job adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol, cast

import structlog
from taskiq import Context, TaskiqDepends

from osu_server.infrastructure.jobs.registry import jobs

if TYPE_CHECKING:
    from taskiq import TaskiqState

    from osu_server.repositories.interfaces.chat_repository import ChatPersistenceResult

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class ChatPersistenceService(Protocol):
    """ChatService persistence use-case surface required by job adapters."""

    async def persist_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult: ...

    async def persist_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult: ...


def get_chat_service(state: TaskiqState) -> ChatPersistenceService | None:
    """Return the ChatService persistence use-case stored in taskiq state."""
    return cast("ChatPersistenceService | None", getattr(state, "chat_service", None))


@jobs.register(task_name="persist_channel_message")
async def persist_channel_message(
    sender_id: int,
    channel_name: str,
    sender_name: str,
    content: str,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Delegate channel message persistence to ChatService."""
    chat_service = get_chat_service(context.state)
    if chat_service is None:
        logger.error(
            "chat_persistence_runtime_unavailable",
            task_name="persist_channel_message",
            sender_id=sender_id,
            sender_name=sender_name,
            channel_name=channel_name,
        )
        return

    _ = await chat_service.persist_channel_message(
        sender_id=sender_id,
        channel_name=channel_name,
        content=content,
    )


@jobs.register(task_name="persist_private_message")
async def persist_private_message(
    sender_id: int,
    target_id: int,
    sender_name: str,
    target_name: str,
    content: str,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Delegate private message persistence to ChatService."""
    chat_service = get_chat_service(context.state)
    if chat_service is None:
        logger.error(
            "chat_persistence_runtime_unavailable",
            task_name="persist_private_message",
            sender_id=sender_id,
            sender_name=sender_name,
            target_id=target_id,
            target_name=target_name,
        )
        return

    _ = await chat_service.persist_private_message(
        sender_id=sender_id,
        target_id=target_id,
        content=content,
    )


__all__ = [
    "ChatPersistenceService",
    "get_chat_service",
    "persist_channel_message",
    "persist_private_message",
]
