"""ChatRepository Protocol and chat history persistence result types."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from osu_server.domain.chat import ChatPersistenceFailureReason, ChatPersistenceResult


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
