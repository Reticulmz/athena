"""Chat history query use-cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries import (
        ChatHistoryMessage,
        ChatHistoryQueryRepository,
    )


@dataclass(frozen=True, slots=True)
class ListChannelMessagesQueryInput:
    """Channel chat history query input."""

    channel_name: str
    limit: int
    before_message_id: int | None = None


@dataclass(frozen=True, slots=True)
class ListPrivateMessagesQueryInput:
    """Private chat history query input."""

    user_id: int
    peer_user_id: int
    limit: int
    before_message_id: int | None = None


@dataclass(frozen=True, slots=True)
class ChatHistoryQueryResult:
    """Chat history query result."""

    messages: tuple[ChatHistoryMessage, ...]


class ListChannelMessagesQuery:
    """Read persisted channel chat history."""

    def __init__(self, repository: ChatHistoryQueryRepository) -> None:
        self._repository: ChatHistoryQueryRepository = repository

    async def execute(
        self,
        input_data: ListChannelMessagesQueryInput,
    ) -> ChatHistoryQueryResult:
        messages = await self._repository.list_channel_messages(
            input_data.channel_name,
            limit=input_data.limit,
            before_message_id=input_data.before_message_id,
        )
        return ChatHistoryQueryResult(messages=tuple(messages))


class ListPrivateMessagesQuery:
    """Read persisted private chat history."""

    def __init__(self, repository: ChatHistoryQueryRepository) -> None:
        self._repository: ChatHistoryQueryRepository = repository

    async def execute(
        self,
        input_data: ListPrivateMessagesQueryInput,
    ) -> ChatHistoryQueryResult:
        messages = await self._repository.list_private_messages(
            input_data.user_id,
            input_data.peer_user_id,
            limit=input_data.limit,
            before_message_id=input_data.before_message_id,
        )
        return ChatHistoryQueryResult(messages=tuple(messages))
