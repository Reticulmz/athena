"""channel message の送信可否と persistence work 発行を扱う use-case を提供する.

この module は silence,message length,channel ACL,channel 固有の rate limit を確認する.
受理済み
message は BanchoBot command response とともに delivery result へまとめ,非同期 persistence
work を発行する.
"""

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
    """channel へ送信する message input を表す command.

    Attributes:
        message (SendChannelMessageInput):
            sender,destination,authorization,raw content を含む channel message input.
    """

    message: SendChannelMessageInput


@dataclass(frozen=True, slots=True)
class SendChannelMessageResult:
    """channel message 送信 workflow の受理結果を表す.

    Attributes:
        result (ChannelMessageResult | None):
            delivery target と command response を含む成功結果. 拒否時はNone.
    """

    result: ChannelMessageResult | None


class SendChannelMessageUseCase:
    """channel message の送信可否を検証し,delivery と persistence work を開始する use-case.

    channel delivery query が返す channel 固有の rate limit は config の既定値より優先する.
    message を
    受理した場合だけ BanchoBot command service と persistence work publisher を呼び出す.

    Attributes:
        _channel_delivery_query (ResolveChannelMessageDeliveryQuery):
            sender の channel delivery target と rate-limit metadata を解決する query.
        _command_service (CommandService):
            content に含まれる BanchoBot command を実行する service.
        _session_store (UserSessionLookup): sender session と silence state を検索する store.
        _persistence_publisher (ChatPersistenceWorkPublisher):
            受理済み channel message の durable work を発行する port.
        _rate_limiter (RateLimiter): sender と channel 固有 limit を照合する limiter.
        _config (AppConfig):
            message length と既定 rate limit を提供する application configuration.
    """

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
        """Channel message workflow の query,state,publisher,rate-limit 依存関係を設定する.

        Args:
            channel_delivery_query (ResolveChannelMessageDeliveryQuery):
                channel membership と delivery target を解決する query.
            command_service (CommandService):
                受理済み content に対する BanchoBot command service.
            session_store (UserSessionLookup):
                sender session と silence state を取得する store.
            persistence_publisher (ChatPersistenceWorkPublisher):
                accepted message の durable work を発行する port.
            rate_limiter (RateLimiter): user ごとの送信回数を制限する limiter.
            config (AppConfig):
                message maximum length と既定 rate limit を提供する configuration.

        """
        self._channel_delivery_query: ResolveChannelMessageDeliveryQuery = channel_delivery_query
        self._command_service: CommandService = command_service
        self._session_store: UserSessionLookup = session_store
        self._persistence_publisher: ChatPersistenceWorkPublisher = persistence_publisher
        self._rate_limiter: RateLimiter = rate_limiter
        self._config: AppConfig = config

    async def execute(self, command: SendChannelMessageCommand) -> SendChannelMessageResult:
        """Channel message を検証し,受理時に delivery result と persistence work を作成する.

        Args:
            command (SendChannelMessageCommand):
                sender,channel destination,authorization,content を含む command.

        Returns:
            SendChannelMessageResult: message を受理した場合は delivery target と command
            response を持つ結果.
            silence,validation,ACL,rate limit による拒否時は`result=None`.

        Notes:
            channel 固有の rate limit は config の既定値より優先する. persistence work は
            channel delivery と
            BanchoBot command 実行が成功した後だけ発行する.
        """
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
        """Sender が存在し,現在 silence 中でないかを判定する.

        Args:
            sender_id (int): session と silence state を検索する sender の識別子.

        Returns:
            bool: session が存在し,silence end が未設定または現在時刻以前ならTrue.
            それ以外はFalse.
        """
        session = await self._session_store.get_by_user(sender_id)
        if not session:
            return False
        if session.silence_end and int(time.time()) < session.silence_end:
            logger.info("silenced_user_message_rejected", sender_id=sender_id)
            return False
        return True

    async def _validate_message(self, content: str) -> str | None:
        """Message content が空でなく最大長以内かを検証する.

        Args:
            content (str): sender が送信した raw message text.

        Returns:
            str | None: 受理可能な元の content. 空文字列または設定済み maximum length
            超過ならNone.
        """
        if not content:
            return None
        if len(content) > self._config.message_max_length:
            return None
        return content
