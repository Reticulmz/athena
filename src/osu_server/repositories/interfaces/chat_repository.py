"""ChatRepository Protocol and chat history persistence result types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Self, runtime_checkable


class ChatPersistenceFailureReason(Enum):
    """Typed reasons why accepted chat history could not be persisted."""

    CHANNEL_NOT_FOUND = "channel_not_found"
    STORAGE_ERROR = "storage_error"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


@dataclass(slots=True, frozen=True)
class ChatPersistenceResult:
    """Result of persisting accepted chat history."""

    success: bool
    reason: ChatPersistenceFailureReason | None = None

    def __post_init__(self) -> None:
        """Validate success and failure reason consistency."""
        if self.success and self.reason is not None:
            msg = "successful chat persistence cannot have a reason"
            raise ValueError(msg)
        if not self.success and self.reason is None:
            msg = "failed chat persistence requires a reason"
            raise ValueError(msg)

    @classmethod
    def success_result(cls) -> Self:
        """Return a successful persistence result."""
        return cls(success=True)

    @classmethod
    def failure(cls, reason: ChatPersistenceFailureReason) -> Self:
        """Return a failed persistence result with a typed reason."""
        return cls(success=False, reason=reason)


@runtime_checkable
class ChatRepository(Protocol):
    """Protocol for accepted chat history persistence.

    Preconditions:
        - Inputs come from accepted chat delivery events.
        - Delivery policy, ACL, membership, and command checks already happened.
    Postconditions:
        - Success means chat history was durably stored by the implementation.
        - Failure carries a typed reason instead of silent success.
    """

    async def save_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        """Persist accepted public channel chat history."""
        ...

    async def save_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult:
        """Persist accepted private chat history."""
        ...


__all__ = [
    "ChatPersistenceFailureReason",
    "ChatPersistenceResult",
    "ChatRepository",
]
