"""Persist private message command use-case."""

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
class PersistPrivateMessageCommand:
    """Command to persist a private message."""

    sender_id: int
    target_id: int
    content: str


class PersistPrivateMessageUseCase:
    """Use-case for persisting private messages."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory | None = None,
    ) -> None:
        self._uow_factory: UnitOfWorkFactory | None = uow_factory

    async def execute(self, command: PersistPrivateMessageCommand) -> ChatPersistenceResult:
        """Execute the persist private message command."""
        if self._uow_factory is None:
            result = ChatPersistenceResult.failure(
                ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE
            )
            logger.warning(
                "chat_persistence_failed",
                sender_id=command.sender_id,
                target_id=command.target_id,
                reason=ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE.value,
            )
            return result

        try:
            async with self._uow_factory() as uow:
                result = await uow.chat.save_private_message(
                    sender_id=command.sender_id,
                    target_id=command.target_id,
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
                target_id=command.target_id,
                reason=ChatPersistenceFailureReason.STORAGE_ERROR.value,
            )
            return ChatPersistenceResult.failure(ChatPersistenceFailureReason.STORAGE_ERROR)

        if not result.success:
            logger.warning(
                "chat_persistence_failed",
                sender_id=command.sender_id,
                target_id=command.target_id,
                reason=result.reason.value if result.reason is not None else None,
            )

        return result
