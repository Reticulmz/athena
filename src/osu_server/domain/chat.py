"""Domain models for chat use-cases."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class ChatSender:
    user_id: int
    username: str


@dataclass(slots=True, frozen=True)
class ChannelChatDestination:
    name: str


@dataclass(slots=True, frozen=True)
class PrivateChatDestination:
    username: str


@dataclass(slots=True, frozen=True)
class ChannelChatAuthorization:
    privileges: int = 0
    role_ids: tuple[int, ...] = ()


@dataclass(slots=True, frozen=True)
class SendChannelMessageInput:
    sender: ChatSender
    destination: ChannelChatDestination
    content: str
    authorization: ChannelChatAuthorization = field(default_factory=ChannelChatAuthorization)


@dataclass(slots=True, frozen=True)
class SendPrivateMessageInput:
    sender: ChatSender
    destination: PrivateChatDestination
    content: str


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
