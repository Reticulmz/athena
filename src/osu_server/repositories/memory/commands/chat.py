"""In-memory command-side chat repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.chat import (
    ChatPersistenceFailureReason,
    ChatPersistenceResult,
)
from osu_server.repositories.memory.commands.state import (
    InMemoryChannelMessageRecord,
    InMemoryPrivateMessageRecord,
    now_utc,
)

if TYPE_CHECKING:
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryChatCommandRepository:
    """Chat command repository backed by an active in-memory UoW state."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    async def save_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        """Persist accepted public channel chat history."""
        channel_id = self._state.channel_id_by_name.get(channel_name)
        if channel_id is None:
            return ChatPersistenceResult.failure(ChatPersistenceFailureReason.CHANNEL_NOT_FOUND)

        record_id = self._state.next_channel_message_id
        self._state.next_channel_message_id += 1
        self._state.channel_messages_by_id[record_id] = InMemoryChannelMessageRecord(
            id=record_id,
            sender_id=sender_id,
            channel_id=channel_id,
            channel_name=channel_name,
            content=content,
            created_at=now_utc(),
        )
        return ChatPersistenceResult.success_result()

    async def save_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult:
        """Persist accepted private chat history."""
        record_id = self._state.next_private_message_id
        self._state.next_private_message_id += 1
        self._state.private_messages_by_id[record_id] = InMemoryPrivateMessageRecord(
            id=record_id,
            sender_id=sender_id,
            target_id=target_id,
            content=content,
            created_at=now_utc(),
        )
        return ChatPersistenceResult.success_result()
