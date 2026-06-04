from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.chat import (
    ChannelMessageResult,
    PrivateMessageResult,
    SendChannelMessageInput,
    SendPrivateMessageInput,
)
from osu_server.domain.events.channels import ChannelMessageSent, PrivateMessageSent
from osu_server.repositories.interfaces.chat_repository import (
    ChatPersistenceFailureReason,
    ChatPersistenceResult,
)

if TYPE_CHECKING:
    from osu_server.config import AppConfig
    from osu_server.infrastructure.messaging.interfaces import EventBus
    from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
    from osu_server.repositories.interfaces.chat_repository import ChatRepository
    from osu_server.repositories.interfaces.session_store import SessionStore
    from osu_server.services.bancho_bot.command_service import CommandService
    from osu_server.services.channel_service import ChannelService
    from osu_server.services.private_message_service import PMDeliveryResult, PrivateMessageService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class ChatService:
    """Chat orchestrator service for channel and private messages."""

    def __init__(
        self,
        *,
        channel_service: ChannelService,
        private_message_service: PrivateMessageService,
        command_service: CommandService,
        session_store: SessionStore,
        event_bus: EventBus,
        rate_limiter: RateLimiter,
        config: AppConfig,
        chat_repository: ChatRepository | None = None,
    ) -> None:
        self._channel_service: ChannelService = channel_service
        self._private_message_service: PrivateMessageService = private_message_service
        self._command_service: CommandService = command_service
        self._session_store: SessionStore = session_store
        self._event_bus: EventBus = event_bus
        self._rate_limiter: RateLimiter = rate_limiter
        self._config: AppConfig = config
        self._chat_repository: ChatRepository | None = chat_repository

    async def _check_silence(self, sender_id: int) -> bool:
        session = await self._session_store.get_by_user(sender_id)
        if not session:
            return False  # not online
        if session.silence_end and int(time.time()) < session.silence_end:
            logger.info("silenced_user_message_rejected", sender_id=sender_id)
            return False
        return True

    async def _validate_message(self, content: str) -> str | None:
        if not content:
            return None
        if len(content) > self._config.message_max_length:
            return None
        return content

    async def send_channel_message(
        self,
        message: SendChannelMessageInput,
    ) -> ChannelMessageResult | None:
        sender = message.sender
        destination = message.destination
        authorization = message.authorization

        if not await self._check_silence(sender.user_id):
            return None

        # Check rate limit
        channel = await self._channel_service.get_channel(destination.name)
        limit = self._config.rate_limit_messages
        window = self._config.rate_limit_window
        if channel:
            if channel.rate_limit_messages is not None:
                limit = channel.rate_limit_messages
            if channel.rate_limit_window is not None:
                window = channel.rate_limit_window

        if not await self._rate_limiter.check(sender.user_id, limit, window):
            logger.info("rate_limit_exceeded", sender_id=sender.user_id)
            return None

        valid_content = await self._validate_message(message.content)
        if not valid_content:
            return None

        # Routing — resolve delivery targets
        targets = await self._channel_service.get_delivery_targets(
            sender_id=sender.user_id,
            user_privileges=authorization.privileges,
            user_role_ids=list(authorization.role_ids),
            channel_name=destination.name,
        )
        if targets is None:
            return None

        # Command detection (after routing per design pipeline)
        command_response = await self._command_service.execute(
            sender.user_id, sender.username, destination.name, valid_content
        )

        # Fire persistence event — commands are also delivered to members
        await self._event_bus.fire(
            ChannelMessageSent(
                sender_id=sender.user_id,
                sender_name=sender.username,
                channel_name=destination.name,
                content=valid_content,
            )
        )

        return ChannelMessageResult(
            delivered_to=targets,
            content=valid_content,
            command_responses=(command_response,) if command_response is not None else (),
        )

    async def persist_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        if self._chat_repository is None:
            result = ChatPersistenceResult.failure(
                ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE
            )
            logger.warning(
                "chat_persistence_failed",
                sender_id=sender_id,
                channel_name=channel_name,
                reason=ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE.value,
            )
            return result

        result = await self._chat_repository.save_channel_message(
            sender_id=sender_id,
            channel_name=channel_name,
            content=content,
        )
        if not result.success:
            event_name = "chat_persistence_failed"
            if result.reason is ChatPersistenceFailureReason.CHANNEL_NOT_FOUND:
                event_name = "chat_persistence_channel_not_found"
            logger.warning(
                event_name,
                sender_id=sender_id,
                channel_name=channel_name,
                reason=result.reason.value if result.reason is not None else None,
            )
        return result

    async def persist_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult:
        if self._chat_repository is None:
            result = ChatPersistenceResult.failure(
                ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE
            )
            logger.warning(
                "chat_persistence_failed",
                sender_id=sender_id,
                target_id=target_id,
                reason=ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE.value,
            )
            return result

        result = await self._chat_repository.save_private_message(
            sender_id=sender_id,
            target_id=target_id,
            content=content,
        )
        if not result.success:
            logger.warning(
                "chat_persistence_failed",
                sender_id=sender_id,
                target_id=target_id,
                reason=result.reason.value if result.reason is not None else None,
            )
        return result

    async def send_private_message(
        self,
        message: SendPrivateMessageInput,
    ) -> PrivateMessageResult | None:
        sender = message.sender
        destination = message.destination

        if not await self._check_silence(sender.user_id):
            return None

        # Check rate limit
        if not await self._rate_limiter.check(
            sender.user_id, self._config.rate_limit_messages, self._config.rate_limit_window
        ):
            logger.info("rate_limit_exceeded", sender_id=sender.user_id)
            return None

        valid_content = await self._validate_message(message.content)
        if not valid_content:
            return None

        # Command detection
        command_response = await self._command_service.execute(
            sender.user_id, sender.username, destination.username, valid_content
        )

        # Routing — resolve PM target
        pm_result: PMDeliveryResult = await self._private_message_service.deliver_message(
            target_name=destination.username,
        )

        if not pm_result.success:
            # Target user does not exist — return error indicator.
            # Transport layer sends error notification via BanchoBot PM.
            return PrivateMessageResult(
                target_id=None,
                is_online=False,
                content=valid_content,
                command_responses=(),
            )

        # Fire persistence event
        assert pm_result.target_id is not None  # success=True guarantees target_id
        await self._event_bus.fire(
            PrivateMessageSent(
                sender_id=sender.user_id,
                sender_name=sender.username,
                target_id=pm_result.target_id,
                target_name=destination.username,
                content=valid_content,
            )
        )

        return PrivateMessageResult(
            target_id=pm_result.target_id,
            is_online=pm_result.is_online,
            content=valid_content,
            command_responses=(command_response,) if command_response is not None else (),
        )
