"""app processから利用するchat workflow providerを構成する."""

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
    """app向けchat送信workflowをAPP scopeで登録する.

    Attributes:
        scope (Scope): app container内で共有するDishkaのAPP scope.
    """

    scope = Scope.APP

    @provide
    def private_message_target_query(
        self,
        user_repository: UserQueryRepository,
        session_store: SessionStore,
    ) -> ResolvePrivateMessageTargetQuery:
        """Private messageの宛先userとonline状態を解決するqueryを構成する.

        Args:
            user_repository (UserQueryRepository): 送信先userを検索するread repository.
            session_store (SessionStore): online sessionを検索するvolatile store.

        Returns:
            ResolvePrivateMessageTargetQuery: usernameから宛先userとonline状態を解決するquery.
        """
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
        """Private messageの宛先とonline状態を解決するserviceを構成する.

        Args:
            user_repo (UserQueryRepository): user情報を検索するread repository.
            session_store (SessionStore): session情報を検索するvolatile store.

        Returns:
            PrivateMessageService: private messageの宛先userとonline状態を解決するservice.
        """
        return PrivateMessageService(user_repo=user_repo, session_store=session_store)

    @provide
    def command_service(self) -> CommandService:
        """組み込みBanchoBot command registryを持つcommand serviceを構成する.

        Returns:
            CommandService: Athenaが標準で提供するchat commandを解決するservice.
        """
        return CommandService(create_builtin_registry())

    @provide
    def chat_persistence_work_publisher(
        self,
        broker: AsyncBroker,
    ) -> ChatPersistenceWorkPublisher:
        """Chat history保存jobをTaskiqへpublishするportを構成する.

        Args:
            broker (AsyncBroker): chat persistence taskをenqueueするTaskiq broker.

        Returns:
            ChatPersistenceWorkPublisher: message保存workをworkerへ配送するpublisher.
        """
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
        """Channel message送信commandを配送,rate limit,persistence依存で構成する.

        Args:
            channel_delivery_query (ResolveChannelMessageDeliveryQuery):
                channel配送先を解決するquery.
            command_service (CommandService): BanchoBot commandを解決するservice.
            session_store (SessionStore): senderとrecipient sessionを読むvolatile store.
            persistence_publisher (ChatPersistenceWorkPublisher):
                history保存workをworkerへ配送するport.
            rate_limiter (RateLimiter): sender単位の送信頻度を制限するstore.
            config (AppConfig): chat送信に必要な実行時設定.

        Returns:
            SendChannelMessageUseCase: channel messageを検証,配送,非同期永続化するcommand.
        """
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
        """Private message送信commandを送信先,friend関係,rate limit依存で構成する.

        Args:
            target_query (ResolvePrivateMessageTargetQuery): recipient sessionを解決するquery.
            friend_relationship_query (CheckFriendRelationshipQuery):
                senderとrecipientのfriend関係を調べるquery.
            command_service (CommandService): BanchoBot commandを解決するservice.
            session_store (SessionStore): senderとrecipient sessionを読むvolatile store.
            persistence_publisher (ChatPersistenceWorkPublisher):
                history保存workをworkerへ配送するport.
            rate_limiter (RateLimiter): sender単位の送信頻度を制限するstore.
            config (AppConfig): private message送信に必要な実行時設定.

        Returns:
            SendPrivateMessageUseCase: private messageを検証,配送,非同期永続化するcommand.
        """
        return SendPrivateMessageUseCase(
            target_query=target_query,
            friend_relationship_query=friend_relationship_query,
            command_service=command_service,
            session_store=session_store,
            persistence_publisher=persistence_publisher,
            rate_limiter=rate_limiter,
            config=config,
        )
