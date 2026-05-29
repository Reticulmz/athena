from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.events.channels import ChannelMessageSent, PrivateMessageSent

if TYPE_CHECKING:
    from osu_server.config import AppConfig
    from osu_server.infrastructure.messaging.interfaces import EventBus
    from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
    from osu_server.repositories.interfaces.session_store import SessionStore
    from osu_server.services.channel_service import ChannelService
    from osu_server.services.command_service import CommandService
    from osu_server.services.private_message_service import PrivateMessageService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


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
    ) -> None:
        self._channel_service: ChannelService = channel_service
        self._private_message_service: PrivateMessageService = private_message_service
        self._command_service: CommandService = command_service
        self._session_store: SessionStore = session_store
        self._event_bus: EventBus = event_bus
        self._rate_limiter: RateLimiter = rate_limiter
        self._config: AppConfig = config

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
            return content[: self._config.message_max_length]
        return content

    async def send_channel_message(
        self,
        sender_id: int,
        sender_name: str,
        channel_name: str,
        content: str,
        user_privileges: int = 0,
        user_role_ids: list[int] | None = None,
    ) -> ChannelMessageResult | None:
        if not await self._check_silence(sender_id):
            return None

        # Check rate limit
        channel = await self._channel_service.get_channel(channel_name)
        limit = self._config.rate_limit_messages
        window = self._config.rate_limit_window
        if channel:
            if channel.rate_limit_messages is not None:
                limit = channel.rate_limit_messages
            if channel.rate_limit_window is not None:
                window = channel.rate_limit_window

        if not await self._rate_limiter.check(sender_id, limit, window):
            logger.info("rate_limit_exceeded", sender_id=sender_id)
            return None

        valid_content = await self._validate_message(content)
        if not valid_content:
            return None

        command_res = await self._command_service.execute(
            sender_id, sender_name, channel_name, valid_content
        )
        command_response = None
        if command_res:
            command_response = ChatCommandResponse(target=command_res[0], content=command_res[1])
            # Do not persist commands, just return targets = None
            return ChannelMessageResult(
                delivered_to=None,
                content=valid_content,
                command_response=command_response,
            )

        if user_role_ids is None:
            user_role_ids = []

        targets = await self._channel_service.get_delivery_targets(
            sender_id=sender_id,
            user_privileges=user_privileges,
            user_role_ids=user_role_ids,
            channel_name=channel_name,
        )

        await self._event_bus.fire(
            ChannelMessageSent(
                sender_id=sender_id,
                sender_name=sender_name,
                channel_name=channel_name,
                content=valid_content,
            )
        )

        return ChannelMessageResult(
            delivered_to=targets,
            content=valid_content,
            command_response=None,
        )

    async def send_private_message(
        self,
        sender_id: int,
        sender_name: str,
        target_name: str,
        content: str,
    ) -> PrivateMessageResult | None:
        if not await self._check_silence(sender_id):
            return None

        # Check rate limit
        if not await self._rate_limiter.check(
            sender_id, self._config.rate_limit_messages, self._config.rate_limit_window
        ):
            logger.info("rate_limit_exceeded", sender_id=sender_id)
            return None

        valid_content = await self._validate_message(content)
        if not valid_content:
            return None

        command_res = await self._command_service.execute(
            sender_id, sender_name, target_name, valid_content
        )
        command_response = None
        if command_res:
            command_response = ChatCommandResponse(target=command_res[0], content=command_res[1])
            return PrivateMessageResult(
                target_id=None,
                is_online=False,
                content=valid_content,
                command_response=command_response,
            )

        target_info = await self._private_message_service.resolve_target(target_name)
        exists, target_id, is_online = target_info

        if exists and target_id is not None:
            await self._event_bus.fire(
                PrivateMessageSent(
                    sender_id=sender_id,
                    sender_name=sender_name,
                    target_id=target_id,
                    target_name=target_name,
                    content=valid_content,
                )
            )

        return PrivateMessageResult(
            target_id=target_id if exists else None,
            is_online=is_online,
            content=valid_content,
            command_response=None,
        )
