"""Send channel message command use-case."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.chat import ChannelMessageResult
from osu_server.services.commands.chat.persistence_work import ChannelMessagePersistenceWork
from osu_server.services.queries.chat import ResolveChannelMessageDeliveryQueryInput

if TYPE_CHECKING:
    from osu_server.config import AppConfig
    from osu_server.domain.chat import SendChannelMessageInput
    from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
    from osu_server.repositories.interfaces.session_store import UserSessionLookup
    from osu_server.services.commands.chat.bancho_bot.command_service import CommandService
    from osu_server.services.commands.chat.persistence_work import ChatPersistenceWorkPublisher
    from osu_server.services.queries.chat import ResolveChannelMessageDeliveryQuery

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(frozen=True, slots=True)
class SendChannelMessageCommand:
    """Command to send a message to a channel."""

    message: SendChannelMessageInput


@dataclass(frozen=True, slots=True)
class SendChannelMessageResult:
    """Result of sending a channel message."""

    result: ChannelMessageResult | None


class SendChannelMessageUseCase:
    """Use-case for sending messages to channels."""

    def __init__(
        self,
        *,
        channel_delivery_query: ResolveChannelMessageDeliveryQuery,
        command_service: CommandService,
        session_store: UserSessionLookup,
        persistence_publisher: ChatPersistenceWorkPublisher,
        rate_limiter: RateLimiter,
        config: AppConfig,
    ) -> None:
        self._channel_delivery_query: ResolveChannelMessageDeliveryQuery = channel_delivery_query
        self._command_service: CommandService = command_service
        self._session_store: UserSessionLookup = session_store
        self._persistence_publisher: ChatPersistenceWorkPublisher = persistence_publisher
        self._rate_limiter: RateLimiter = rate_limiter
        self._config: AppConfig = config

    async def execute(self, command: SendChannelMessageCommand) -> SendChannelMessageResult:
        """Execute the send channel message command."""
        message = command.message
        sender = message.sender
        destination = message.destination
        authorization = message.authorization

        # Check silence
        if not await self._check_silence(sender.user_id):
            return SendChannelMessageResult(result=None)

        # Validate message
        valid_content = await self._validate_message(message.content)
        if not valid_content:
            return SendChannelMessageResult(result=None)

        # Resolve delivery targets and channel-specific rate-limit metadata.
        delivery = await self._channel_delivery_query.execute(
            ResolveChannelMessageDeliveryQueryInput(
                sender_id=sender.user_id,
                channel_name=destination.name,
                user_privileges=authorization.privileges,
                user_role_ids=authorization.role_ids,
            )
        )
        if delivery.delivered_to is None:
            return SendChannelMessageResult(result=None)

        limit = self._config.rate_limit_messages
        window = self._config.rate_limit_window
        if delivery.channel is not None:
            if delivery.channel.rate_limit_messages is not None:
                limit = delivery.channel.rate_limit_messages
            if delivery.channel.rate_limit_window is not None:
                window = delivery.channel.rate_limit_window

        # Check rate limit
        if not await self._rate_limiter.check(sender.user_id, limit, window):
            logger.info("rate_limit_exceeded", sender_id=sender.user_id)
            return SendChannelMessageResult(result=None)

        # Execute commands
        command_responses = await self._command_service.execute(
            sender.user_id,
            sender.username,
            destination.name,
            valid_content,
            authorization=authorization,
        )

        await self._persistence_publisher.publish_channel_message(
            ChannelMessagePersistenceWork(
                sender_id=sender.user_id,
                sender_name=sender.username,
                channel_name=destination.name,
                content=valid_content,
            )
        )

        result = ChannelMessageResult(
            delivered_to=set(delivery.delivered_to),
            content=valid_content,
            command_responses=command_responses,
        )
        return SendChannelMessageResult(result=result)

    async def _check_silence(self, sender_id: int) -> bool:
        """Check if sender is silenced."""
        session = await self._session_store.get_by_user(sender_id)
        if not session:
            return False
        if session.silence_end and int(time.time()) < session.silence_end:
            logger.info("silenced_user_message_rejected", sender_id=sender_id)
            return False
        return True

    async def _validate_message(self, content: str) -> str | None:
        """Validate message content."""
        if not content:
            return None
        if len(content) > self._config.message_max_length:
            return None
        return content
