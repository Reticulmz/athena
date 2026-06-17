"""App-facing chat workflow providers."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope
from taskiq import AsyncBroker

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.jobs.chat_persistence_publisher import TaskiqChatPersistenceWorkPublisher
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.commands.chat import (
    ChatPersistenceWorkPublisher,
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
from osu_server.services.queries.identity import CheckFriendRelationshipQuery

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    AsyncBroker,
    ChatPersistenceWorkPublisher,
    CheckFriendRelationshipQuery,
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
    def chat_persistence_work_publisher(
        self,
        broker: AsyncBroker,
    ) -> ChatPersistenceWorkPublisher:
        return TaskiqChatPersistenceWorkPublisher(broker)

    @provide
    def send_channel_message_use_case(
        self,
        channel_delivery_query: ResolveChannelMessageDeliveryQuery,
        command_service: CommandService,
        session_store: SessionStore,
        persistence_publisher: ChatPersistenceWorkPublisher,
        rate_limiter: RateLimiter,
        config: AppConfig,
    ) -> SendChannelMessageUseCase:
        return SendChannelMessageUseCase(
            channel_delivery_query=channel_delivery_query,
            command_service=command_service,
            session_store=session_store,
            persistence_publisher=persistence_publisher,
            rate_limiter=rate_limiter,
            config=config,
        )

    @provide
    def send_private_message_use_case(
        self,
        target_query: ResolvePrivateMessageTargetQuery,
        friend_relationship_query: CheckFriendRelationshipQuery,
        command_service: CommandService,
        session_store: SessionStore,
        persistence_publisher: ChatPersistenceWorkPublisher,
        rate_limiter: RateLimiter,
        config: AppConfig,
    ) -> SendPrivateMessageUseCase:
        return SendPrivateMessageUseCase(
            target_query=target_query,
            friend_relationship_query=friend_relationship_query,
            command_service=command_service,
            session_store=session_store,
            persistence_publisher=persistence_publisher,
            rate_limiter=rate_limiter,
            config=config,
        )
