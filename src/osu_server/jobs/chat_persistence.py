"""chat persistence command use-case を呼び出す Taskiq adapter を定義する."""

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
    """channel message persistence job が要求する use-case 境界を表す."""

    async def execute(self, command: PersistChannelMessageCommand) -> ChatPersistenceResult:
        """Channel message persistence command を実行する.

        Args:
            command (PersistChannelMessageCommand): durable storage へ渡す command.

        Returns:
            ChatPersistenceResult: persistence の結果.

        Raises:
            Exception: use-case の処理に失敗した場合.
        """
        ...


class PrivateMessagePersistenceUseCase(Protocol):
    """private message persistence job が要求する use-case 境界を表す."""

    async def execute(self, command: PersistPrivateMessageCommand) -> ChatPersistenceResult:
        """Private message persistence command を実行する.

        Args:
            command (PersistPrivateMessageCommand): durable storage へ渡す command.

        Returns:
            ChatPersistenceResult: persistence の結果.

        Raises:
            Exception: use-case の処理に失敗した場合.
        """
        ...


def get_channel_message_persistence_use_case(
    state: TaskiqState,
) -> ChannelMessagePersistenceUseCase | None:
    """Taskiq state から channel message persistence use-case を返す.

    Args:
        state (TaskiqState): worker runtime が保持する Taskiq state.

    Returns:
        ChannelMessagePersistenceUseCase | None: 登録済み use-case または未登録時の None.
    """
    return cast(
        "ChannelMessagePersistenceUseCase | None",
        getattr(state, "persist_channel_message_use_case", None),
    )


def get_private_message_persistence_use_case(
    state: TaskiqState,
) -> PrivateMessagePersistenceUseCase | None:
    """Taskiq state から private message persistence use-case を返す.

    Args:
        state (TaskiqState): worker runtime が保持する Taskiq state.

    Returns:
        PrivateMessagePersistenceUseCase | None: 登録済み use-case または未登録時の None.
    """
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
    """Channel message の persistence を command use-case に委譲する.

    Args:
        sender_id (int): message を送信した user の ID.
        channel_name (str): message の送信先 channel 名.
        sender_name (str): 運用ログへ記録する送信者名.
        content (str): persist する message 本文.
        context (Context): use-case を取得する Taskiq runtime context.

    Returns:
        None: command use-case を実行して完了する.

    Raises:
        RuntimeError: channel message persistence use-case が未登録の場合.
    """
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
    """Private message の persistence を command use-case に委譲する.

    Args:
        sender_id (int): message を送信した user の ID.
        target_id (int): message を受信する user の ID.
        sender_name (str): 運用ログへ記録する送信者名.
        target_name (str): 運用ログへ記録する受信者名.
        content (str): persist する message 本文.
        context (Context): use-case を取得する Taskiq runtime context.

    Returns:
        None: command use-case を実行して完了する.

    Raises:
        RuntimeError: private message persistence use-case が未登録の場合.
    """
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
