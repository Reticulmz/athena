"""Query-side chat history repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class ChatHistoryMessage:
    """Read model for persisted chat history."""

    id: int
    sender_id: int
    content: str
    created_at: datetime


class ChatHistoryQueryRepository(Protocol):
    """Read-only access to persisted chat history."""

    async def list_channel_messages(
        self,
        channel_name: str,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[ChatHistoryMessage]:
        """Return channel history in reverse chronological order."""
        ...

    async def list_private_messages(
        self,
        user_id: int,
        peer_user_id: int,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[ChatHistoryMessage]:
        """Return private message history in reverse chronological order."""
        ...
