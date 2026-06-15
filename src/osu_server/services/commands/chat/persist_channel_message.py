"""Persist channel message command use-case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.chat import (
    ChatPersistenceFailureReason,
    ChatPersistenceResult,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(frozen=True, slots=True)
class PersistChannelMessageCommand:
    """Command to persist a channel message."""

    sender_id: int
    channel_name: str
    content: str


class PersistChannelMessageUseCase:
    """Use-case for persisting channel messages."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory | None = None,
    ) -> None:
        self._uow_factory: UnitOfWorkFactory | None = uow_factory

    async def execute(self, command: PersistChannelMessageCommand) -> ChatPersistenceResult:
        """Execute the persist channel message command."""
        if self._uow_factory is None:
            result = ChatPersistenceResult.failure(
                ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE
            )
            logger.warning(
                "chat_persistence_failed",
                sender_id=command.sender_id,
                channel_name=command.channel_name,
                reason=ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE.value,
            )
            return result

        try:
            async with self._uow_factory() as uow:
                result = await uow.chat.save_channel_message(
                    sender_id=command.sender_id,
                    channel_name=command.channel_name,
                    content=command.content,
                )
                if result.success:
                    await uow.commit()
                else:
                    await uow.rollback()
        except Exception:
            logger.exception(
                "chat_persistence_failed",
                sender_id=command.sender_id,
                channel_name=command.channel_name,
                reason=ChatPersistenceFailureReason.STORAGE_ERROR.value,
            )
            return ChatPersistenceResult.failure(ChatPersistenceFailureReason.STORAGE_ERROR)

        if not result.success:
            event_name = "chat_persistence_failed"
            if result.reason is ChatPersistenceFailureReason.CHANNEL_NOT_FOUND:
                event_name = "chat_persistence_channel_not_found"
            logger.warning(
                event_name,
                sender_id=command.sender_id,
                channel_name=command.channel_name,
                reason=result.reason.value if result.reason is not None else None,
            )

        return result
