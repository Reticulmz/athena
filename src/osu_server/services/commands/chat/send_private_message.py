"""Send private message command use-case."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.chat import PrivateMessageResult
from osu_server.domain.events.channels import PrivateMessageSent
from osu_server.services.queries.chat import ResolvePrivateMessageTargetQueryInput

if TYPE_CHECKING:
    from osu_server.config import AppConfig
    from osu_server.domain.chat import SendPrivateMessageInput
    from osu_server.infrastructure.messaging.interfaces import EventBus
    from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
    from osu_server.repositories.interfaces.session_store import SessionStore
    from osu_server.services.bancho_bot.command_service import CommandService
    from osu_server.services.queries.chat import ResolvePrivateMessageTargetQuery

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(frozen=True, slots=True)
class SendPrivateMessageCommand:
    """Command to send a private message."""

    message: SendPrivateMessageInput


@dataclass(frozen=True, slots=True)
class SendPrivateMessageResult:
    """Result of sending a private message."""

    result: PrivateMessageResult | None


class SendPrivateMessageUseCase:
    """Use-case for sending private messages."""

    def __init__(
        self,
        *,
        target_query: ResolvePrivateMessageTargetQuery,
        command_service: CommandService,
        session_store: SessionStore,
        event_bus: EventBus,
        rate_limiter: RateLimiter,
        config: AppConfig,
    ) -> None:
        self._target_query: ResolvePrivateMessageTargetQuery = target_query
        self._command_service: CommandService = command_service
        self._session_store: SessionStore = session_store
        self._event_bus: EventBus = event_bus
        self._rate_limiter: RateLimiter = rate_limiter
        self._config: AppConfig = config

    async def execute(self, command: SendPrivateMessageCommand) -> SendPrivateMessageResult:
        """Execute the send private message command."""
        message = command.message
        sender = message.sender
        destination = message.destination

        # Check silence
        if not await self._check_silence(sender.user_id):
            return SendPrivateMessageResult(result=None)

        # Check rate limit
        if not await self._rate_limiter.check(
            sender.user_id,
            self._config.rate_limit_messages,
            self._config.rate_limit_window,
        ):
            logger.info("rate_limit_exceeded", sender_id=sender.user_id)
            return SendPrivateMessageResult(result=None)

        # Validate message
        valid_content = await self._validate_message(message.content)
        if not valid_content:
            return SendPrivateMessageResult(result=None)

        # Execute commands
        command_responses = await self._command_service.execute(
            sender.user_id,
            sender.username,
            destination.username,
            valid_content,
            authorization=message.authorization,
        )

        # Resolve PM target
        pm_result = await self._target_query.execute(
            ResolvePrivateMessageTargetQueryInput(target_name=destination.username),
        )

        if not pm_result.exists:
            return SendPrivateMessageResult(
                result=PrivateMessageResult(
                    target_id=None,
                    is_online=False,
                    content=valid_content,
                    command_responses=(),
                )
            )

        # Fire event for persistence (success guarantees target_id is not None)
        assert pm_result.target_id is not None
        target_id: int = pm_result.target_id
        await self._event_bus.fire(
            PrivateMessageSent(
                sender_id=sender.user_id,
                sender_name=sender.username,
                target_id=target_id,
                target_name=destination.username,
                content=valid_content,
            )
        )

        result = PrivateMessageResult(
            target_id=target_id,
            is_online=pm_result.is_online,
            content=valid_content,
            command_responses=command_responses,
        )
        return SendPrivateMessageResult(result=result)

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
