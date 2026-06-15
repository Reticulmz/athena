"""Taskiq chat persistence job adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol, cast

import structlog
from taskiq import Context, TaskiqDepends

from osu_server.infrastructure.jobs.registry import jobs
from osu_server.services.commands.chat import (
    PersistChannelMessageCommand,
    PersistPrivateMessageCommand,
)

if TYPE_CHECKING:
    from taskiq import TaskiqState

    from osu_server.domain.chat import ChatPersistenceResult

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class ChannelMessagePersistenceUseCase(Protocol):
    """Channel message persistence use-case surface required by job adapters."""

    async def execute(self, command: PersistChannelMessageCommand) -> ChatPersistenceResult: ...


class PrivateMessagePersistenceUseCase(Protocol):
    """Private message persistence use-case surface required by job adapters."""

    async def execute(self, command: PersistPrivateMessageCommand) -> ChatPersistenceResult: ...


def get_channel_message_persistence_use_case(
    state: TaskiqState,
) -> ChannelMessagePersistenceUseCase | None:
    """Return the channel message persistence use-case from taskiq state."""
    return cast(
        "ChannelMessagePersistenceUseCase | None",
        getattr(state, "persist_channel_message_use_case", None),
    )


def get_private_message_persistence_use_case(
    state: TaskiqState,
) -> PrivateMessagePersistenceUseCase | None:
    """Return the private message persistence use-case from taskiq state."""
    return cast(
        "PrivateMessagePersistenceUseCase | None",
        getattr(state, "persist_private_message_use_case", None),
    )


@jobs.register(task_name="persist_channel_message")
async def persist_channel_message(
    sender_id: int,
    channel_name: str,
    sender_name: str,
    content: str,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Delegate channel message persistence to the command use-case."""
    use_case = get_channel_message_persistence_use_case(context.state)
    if use_case is None:
        logger.error(
            "chat_persistence_runtime_unavailable",
            task_name="persist_channel_message",
            sender_id=sender_id,
            sender_name=sender_name,
            channel_name=channel_name,
        )
        msg = "channel message persistence use-case is not registered"
        raise RuntimeError(msg)

    _ = await use_case.execute(
        PersistChannelMessageCommand(
            sender_id=sender_id,
            channel_name=channel_name,
            content=content,
        )
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
    """Delegate private message persistence to the command use-case."""
    use_case = get_private_message_persistence_use_case(context.state)
    if use_case is None:
        logger.error(
            "chat_persistence_runtime_unavailable",
            task_name="persist_private_message",
            sender_id=sender_id,
            sender_name=sender_name,
            target_id=target_id,
            target_name=target_name,
        )
        msg = "private message persistence use-case is not registered"
        raise RuntimeError(msg)

    _ = await use_case.execute(
        PersistPrivateMessageCommand(
            sender_id=sender_id,
            target_id=target_id,
            content=content,
        )
    )


__all__ = [
    "ChannelMessagePersistenceUseCase",
    "PrivateMessagePersistenceUseCase",
    "get_channel_message_persistence_use_case",
    "get_private_message_persistence_use_case",
    "persist_channel_message",
    "persist_private_message",
]
