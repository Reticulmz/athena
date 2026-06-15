"""Chat persistence durable-work publishing boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ChannelMessagePersistenceWork:
    """Accepted channel message persistence work."""

    sender_id: int
    sender_name: str
    channel_name: str
    content: str


@dataclass(frozen=True, slots=True)
class PrivateMessagePersistenceWork:
    """Accepted private message persistence work."""

    sender_id: int
    sender_name: str
    target_id: int
    target_name: str
    content: str


class ChatPersistenceWorkPublisher(Protocol):
    """Starts persistence work for accepted chat messages."""

    async def publish_channel_message(
        self,
        work: ChannelMessagePersistenceWork,
    ) -> None:
        """Publish accepted channel message persistence work."""
        ...

    async def publish_private_message(
        self,
        work: PrivateMessagePersistenceWork,
    ) -> None:
        """Publish accepted private message persistence work."""
        ...
