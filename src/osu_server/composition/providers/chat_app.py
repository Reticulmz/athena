"""App-facing chat workflow providers."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.infrastructure.messaging.interfaces import EventBus
from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.commands.chat import (
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
)
from osu_server.services.commands.chat.bancho_bot.command_service import CommandService
from osu_server.services.commands.chat.bancho_bot.commands import create_builtin_registry
from osu_server.services.queries.chat import (
    ResolveChannelMessageDeliveryQuery,
    ResolvePrivateMessageTargetQuery,
)
from osu_server.services.queries.chat.private_message_service import PrivateMessageService

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    EventBus,
    RateLimiter,
    ResolveChannelMessageDeliveryQuery,
    ResolvePrivateMessageTargetQuery,
    SessionStore,
    UserQueryRepository,
)


@final
class ChatAppProviderSet(Provider):
    """Providers for app-facing chat send workflows."""

    scope = Scope.APP

    @provide
    def private_message_target_query(
        self,
        user_repository: UserQueryRepository,
        session_store: SessionStore,
    ) -> ResolvePrivateMessageTargetQuery:
        return ResolvePrivateMessageTargetQuery(
            user_repository=user_repository,
            session_store=session_store,
        )

    @provide
    def private_message_service(
        self,
        user_repo: UserQueryRepository,
        session_store: SessionStore,
    ) -> PrivateMessageService:
        return PrivateMessageService(user_repo=user_repo, session_store=session_store)

    @provide
    def command_service(self) -> CommandService:
        return CommandService(create_builtin_registry())

    @provide
    def send_channel_message_use_case(
        self,
        channel_delivery_query: ResolveChannelMessageDeliveryQuery,
        command_service: CommandService,
        session_store: SessionStore,
        event_bus: EventBus,
        rate_limiter: RateLimiter,
        config: AppConfig,
    ) -> SendChannelMessageUseCase:
        return SendChannelMessageUseCase(
            channel_delivery_query=channel_delivery_query,
            command_service=command_service,
            session_store=session_store,
            event_bus=event_bus,
            rate_limiter=rate_limiter,
            config=config,
        )

    @provide
    def send_private_message_use_case(
        self,
        target_query: ResolvePrivateMessageTargetQuery,
        command_service: CommandService,
        session_store: SessionStore,
        event_bus: EventBus,
        rate_limiter: RateLimiter,
        config: AppConfig,
    ) -> SendPrivateMessageUseCase:
        return SendPrivateMessageUseCase(
            target_query=target_query,
            command_service=command_service,
            session_store=session_store,
            event_bus=event_bus,
            rate_limiter=rate_limiter,
            config=config,
        )
