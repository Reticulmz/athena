"""Domain models for chat use-cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Self


class ChatPersistenceFailureReason(Enum):
    """Typed reasons why accepted chat history could not be persisted."""

    CHANNEL_NOT_FOUND = "channel_not_found"
    STORAGE_ERROR = "storage_error"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


class PrivateMessageDeliveryStatus(StrEnum):
    """Target delivery status for player-originated private messages."""

    DELIVERABLE = "deliverable"
    OFFLINE = "offline"
    TARGET_NOT_FOUND = "target_not_found"
    BLOCKED_BY_FRIEND_ONLY = "blocked_by_friend_only"


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
class ChatAuthorization:
    privileges: int = 0
    role_ids: tuple[int, ...] = ()


@dataclass(slots=True, frozen=True)
class SendChannelMessageInput:
    sender: ChatSender
    destination: ChannelChatDestination
    content: str
    authorization: ChatAuthorization = field(default_factory=ChatAuthorization)


@dataclass(slots=True, frozen=True)
class SendPrivateMessageInput:
    sender: ChatSender
    destination: PrivateChatDestination
    content: str
    authorization: ChatAuthorization = field(default_factory=ChatAuthorization)


@dataclass(slots=True, frozen=True)
class ChatPersistenceResult:
    """Result of persisting accepted chat history."""

    success: bool
    reason: ChatPersistenceFailureReason | None = None

    def __post_init__(self) -> None:
        if self.success and self.reason is not None:
            msg = "successful chat persistence cannot have a reason"
            raise ValueError(msg)
        if not self.success and self.reason is None:
            msg = "failed chat persistence requires a reason"
            raise ValueError(msg)

    @classmethod
    def success_result(cls) -> Self:
        return cls(success=True)

    @classmethod
    def failure(cls, reason: ChatPersistenceFailureReason) -> Self:
        return cls(success=False, reason=reason)


@dataclass(slots=True)
class ChatCommandResponse:
    target: str
    content: str


@dataclass(slots=True)
class ChannelMessageResult:
    delivered_to: set[int] | None
    content: str
    command_responses: tuple[ChatCommandResponse, ...] = ()


@dataclass(slots=True)
class PrivateMessageResult:
    target_id: int | None
    is_online: bool
    content: str
    command_responses: tuple[ChatCommandResponse, ...] = ()
    delivery_status: PrivateMessageDeliveryStatus = PrivateMessageDeliveryStatus.DELIVERABLE
