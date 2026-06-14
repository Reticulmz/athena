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
    from osu_server.repositories.interfaces.commands.chat import ChatCommandRepository

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
        chat_repository: ChatCommandRepository | None = None,
    ) -> None:
        self._chat_repository: ChatCommandRepository | None = chat_repository

    async def execute(self, command: PersistPrivateMessageCommand) -> ChatPersistenceResult:
        """Execute the persist private message command."""
        if self._chat_repository is None:
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

        result = await self._chat_repository.save_private_message(
            sender_id=command.sender_id,
            target_id=command.target_id,
            content=command.content,
        )

        if not result.success:
            logger.warning(
                "chat_persistence_failed",
                sender_id=command.sender_id,
                target_id=command.target_id,
                reason=result.reason.value if result.reason is not None else None,
            )

        return result
