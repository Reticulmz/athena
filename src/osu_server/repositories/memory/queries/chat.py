"""In-memory query-side chat history repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.repositories.interfaces.queries import ChatHistoryMessage

if TYPE_CHECKING:
    from osu_server.repositories.memory.commands.state import (
        InMemoryChannelMessageRecord,
        InMemoryPrivateMessageRecord,
    )
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryChatHistoryQueryRepository:
    """Read-only chat history repository that reads committed memory state."""

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def list_channel_messages(
        self,
        channel_name: str,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[ChatHistoryMessage]:
        state = self._factory.snapshot()
        records = [
            record
            for record in state.channel_messages_by_id.values()
            if record.channel_name == channel_name
            and (before_message_id is None or record.id < before_message_id)
        ]
        return [_channel_message_to_read_model(record) for record in _latest_first(records, limit)]

    async def list_private_messages(
        self,
        user_id: int,
        peer_user_id: int,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[ChatHistoryMessage]:
        state = self._factory.snapshot()
        records = [
            record
            for record in state.private_messages_by_id.values()
            if _is_private_pair(record, user_id, peer_user_id)
            and (before_message_id is None or record.id < before_message_id)
        ]
        return [_private_message_to_read_model(record) for record in _latest_first(records, limit)]


def _latest_first[T: InMemoryChannelMessageRecord | InMemoryPrivateMessageRecord](
    records: list[T], limit: int
) -> list[T]:
    if limit <= 0:
        return []
    return sorted(records, key=lambda record: (record.created_at, record.id), reverse=True)[:limit]


def _is_private_pair(
    record: InMemoryPrivateMessageRecord,
    user_id: int,
    peer_user_id: int,
) -> bool:
    return (record.sender_id == user_id and record.target_id == peer_user_id) or (
        record.sender_id == peer_user_id and record.target_id == user_id
    )


def _channel_message_to_read_model(
    record: InMemoryChannelMessageRecord,
) -> ChatHistoryMessage:
    return ChatHistoryMessage(
        id=record.id,
        sender_id=record.sender_id,
        content=record.content,
        created_at=record.created_at,
    )


def _private_message_to_read_model(record: InMemoryPrivateMessageRecord) -> ChatHistoryMessage:
    return ChatHistoryMessage(
        id=record.id,
        sender_id=record.sender_id,
        content=record.content,
        created_at=record.created_at,
    )
