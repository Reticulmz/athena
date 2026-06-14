"""Command-side chat persistence repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.chat import ChatPersistenceResult


class ChatCommandRepository(Protocol):
    """Mutation port for accepted chat history persistence."""

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
