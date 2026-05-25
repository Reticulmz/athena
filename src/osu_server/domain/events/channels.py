"""Channel-related domain events.

Events fired during chat message delivery to trigger downstream
processing (e.g. asynchronous DB persistence via ARQ worker).
"""

from __future__ import annotations

from dataclasses import dataclass

from osu_server.domain.events import Event


@dataclass(frozen=True, slots=True)
class ChannelMessageSent(Event):
    """A message was sent to a public channel."""

    sender_id: int
    sender_name: str
    channel_name: str
    content: str


@dataclass(frozen=True, slots=True)
class PrivateMessageSent(Event):
    """A private message was sent between two users."""

    sender_id: int
    sender_name: str
    target_id: int
    target_name: str
    content: str
