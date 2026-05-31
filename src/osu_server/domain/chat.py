"""Domain models for chat use-case results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ChatCommandResponse:
    target: str
    content: str


@dataclass(slots=True)
class ChannelMessageResult:
    delivered_to: set[int] | None
    content: str
    command_response: ChatCommandResponse | None = None


@dataclass(slots=True)
class PrivateMessageResult:
    target_id: int | None
    is_online: bool
    content: str
    command_response: ChatCommandResponse | None = None
