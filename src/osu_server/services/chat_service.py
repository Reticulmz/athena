from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.services.commands.chat import (
    PersistChannelMessageCommand,
    PersistChannelMessageUseCase,
    PersistPrivateMessageCommand,
    PersistPrivateMessageUseCase,
    SendChannelMessageCommand,
    SendChannelMessageUseCase,
    SendPrivateMessageCommand,
    SendPrivateMessageUseCase,
)

if TYPE_CHECKING:
    from osu_server.config import AppConfig
    from osu_server.domain.chat import (
        ChannelMessageResult,
        ChatPersistenceResult,
        PrivateMessageResult,
        SendChannelMessageInput,
        SendPrivateMessageInput,
    )
    from osu_server.infrastructure.messaging.interfaces import EventBus
    from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
    from osu_server.repositories.interfaces.commands.chat import ChatCommandRepository
    from osu_server.repositories.interfaces.session_store import SessionStore
    from osu_server.services.bancho_bot.command_service import CommandService
    from osu_server.services.channel_service import ChannelService
    from osu_server.services.private_message_service import PrivateMessageService


class ChatService:
    """
    DEPRECATED: Facade for chat use-cases. Use command/query use-cases directly.

    This service will be removed after all call sites migrate to use-cases.
    """

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
        chat_repository: ChatCommandRepository | None = None,
    ) -> None:
        # Initialize use-cases
        self._send_channel_msg: SendChannelMessageUseCase = SendChannelMessageUseCase(
            channel_service=channel_service,
            command_service=command_service,
            session_store=session_store,
            event_bus=event_bus,
            rate_limiter=rate_limiter,
            config=config,
        )
        self._send_private_msg: SendPrivateMessageUseCase = SendPrivateMessageUseCase(
            private_message_service=private_message_service,
            command_service=command_service,
            session_store=session_store,
            event_bus=event_bus,
            rate_limiter=rate_limiter,
            config=config,
        )
        self._persist_channel_msg: PersistChannelMessageUseCase = PersistChannelMessageUseCase(
            chat_repository=chat_repository,
        )
        self._persist_private_msg: PersistPrivateMessageUseCase = PersistPrivateMessageUseCase(
            chat_repository=chat_repository,
        )

    async def send_channel_message(
        self,
        message: SendChannelMessageInput,
    ) -> ChannelMessageResult | None:
        """Send a channel message. Delegates to SendChannelMessageUseCase."""
        result = await self._send_channel_msg.execute(SendChannelMessageCommand(message=message))
        return result.result

    async def send_private_message(
        self,
        message: SendPrivateMessageInput,
    ) -> PrivateMessageResult | None:
        """Send a private message. Delegates to SendPrivateMessageUseCase."""
        result = await self._send_private_msg.execute(SendPrivateMessageCommand(message=message))
        return result.result

    async def persist_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        """Persist a channel message. Delegates to PersistChannelMessageUseCase."""
        return await self._persist_channel_msg.execute(
            PersistChannelMessageCommand(
                sender_id=sender_id,
                channel_name=channel_name,
                content=content,
            )
        )

    async def persist_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult:
        """Persist a private message. Delegates to PersistPrivateMessageUseCase."""
        return await self._persist_private_msg.execute(
            PersistPrivateMessageCommand(
                sender_id=sender_id,
                target_id=target_id,
                content=content,
            )
        )
