"""Worker-side ChatService runtime composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.infrastructure.messaging.memory import InMemoryEventBus
from osu_server.infrastructure.state.valkey.channel_state_store import ValkeyChannelStateStore
from osu_server.infrastructure.state.valkey.rate_limiter import ValkeyRateLimiter
from osu_server.repositories.sqlalchemy.channel_repository import SQLAlchemyChannelRepository
from osu_server.repositories.sqlalchemy.chat_repository import SQLAlchemyChatRepository
from osu_server.repositories.sqlalchemy.user_repository import SQLAlchemyUserRepository
from osu_server.repositories.valkey.session_store import ValkeySessionStore
from osu_server.services.bancho_bot.command_service import CommandService
from osu_server.services.bancho_bot.commands import create_builtin_registry
from osu_server.services.channel_service import ChannelService
from osu_server.services.chat_service import ChatService
from osu_server.services.private_message_service import PrivateMessageService

if TYPE_CHECKING:
    from glide import GlideClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from osu_server.config import AppConfig


def create_worker_chat_service(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    valkey: GlideClient,
    config: AppConfig,
) -> ChatService:
    """Build the worker-side ChatService persistence runtime."""
    session_store = ValkeySessionStore(valkey, ttl=config.session_ttl)
    channel_repo = SQLAlchemyChannelRepository(session_factory)
    channel_state = ValkeyChannelStateStore(valkey)
    channel_service = ChannelService(
        channel_repo=channel_repo,
        channel_state=channel_state,
    )
    user_repo = SQLAlchemyUserRepository(session_factory)
    private_message_service = PrivateMessageService(
        user_repo=user_repo,
        session_store=session_store,
    )
    command_service = CommandService(create_builtin_registry())
    event_bus = InMemoryEventBus()
    rate_limiter = ValkeyRateLimiter(valkey)
    chat_repository = SQLAlchemyChatRepository(session_factory)

    return ChatService(
        channel_service=channel_service,
        private_message_service=private_message_service,
        command_service=command_service,
        session_store=session_store,
        event_bus=event_bus,
        rate_limiter=rate_limiter,
        config=config,
        chat_repository=chat_repository,
    )


__all__ = ["create_worker_chat_service"]
