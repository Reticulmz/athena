"""InMemoryChatRepository for test-time chat history persistence."""

from __future__ import annotations

from osu_server.repositories.interfaces.chat_repository import ChatPersistenceResult

type ChannelMessageRecord = tuple[int, str, str]
type PrivateMessageRecord = tuple[int, int, str]


class InMemoryChatRepository:
    """In-memory implementation of the ChatRepository Protocol."""

    _channel_messages: list[ChannelMessageRecord]
    _private_messages: list[PrivateMessageRecord]

    def __init__(self) -> None:
        self._channel_messages = []
        self._private_messages = []

    @property
    def channel_messages(self) -> tuple[ChannelMessageRecord, ...]:
        """Return persisted channel chat messages."""
        return tuple(self._channel_messages)

    @property
    def private_messages(self) -> tuple[PrivateMessageRecord, ...]:
        """Return persisted private chat messages."""
        return tuple(self._private_messages)

    async def save_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        """Persist accepted public channel chat history."""
        self._channel_messages.append((sender_id, channel_name, content))
        return ChatPersistenceResult.success_result()

    async def save_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult:
        """Persist accepted private chat history."""
        self._private_messages.append((sender_id, target_id, content))
        return ChatPersistenceResult.success_result()


__all__ = [
    "ChannelMessageRecord",
    "InMemoryChatRepository",
    "PrivateMessageRecord",
]
