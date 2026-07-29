"""private message の送信可否と persistence work 発行を扱う use-case を提供する.

この module は sender の silence と rate limit を確認し,target existence,online
state,friend-only
setting を評価する. 受理済み message だけを BanchoBot command service と persistence work
publisher へ渡す.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.chat import PrivateMessageDeliveryStatus, PrivateMessageResult
from osu_server.services.commands.chat.persistence_work import PrivateMessagePersistenceWork
from osu_server.services.queries.chat import ResolvePrivateMessageTargetQueryInput

if TYPE_CHECKING:
    from osu_server.config import AppConfig
    from osu_server.domain.chat import SendPrivateMessageInput
    from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
    from osu_server.repositories.interfaces.session_store import UserSessionLookup
    from osu_server.services.commands.chat.bancho_bot.command_service import CommandService
    from osu_server.services.commands.chat.persistence_work import ChatPersistenceWorkPublisher
    from osu_server.services.queries.chat import ResolvePrivateMessageTargetQuery
    from osu_server.services.queries.identity.friend_relationships import (
        CheckFriendRelationshipQueryUseCase,
    )

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(frozen=True, slots=True)
class SendPrivateMessageCommand:
    """private message を送信する input を表す command.

    Attributes:
        message (SendPrivateMessageInput):
            sender,target,authorization,raw content を含む private message input.
    """

    message: SendPrivateMessageInput


@dataclass(frozen=True, slots=True)
class SendPrivateMessageResult:
    """private message 送信 workflow の結果を表す.

    Attributes:
        result (PrivateMessageResult | None):
            target status と command response を含む結果. sender 側の拒否時はNone.
    """

    result: PrivateMessageResult | None


class SendPrivateMessageUseCase:
    """private message の送信可否を検証し,delivery と persistence work を開始する use-case.

    target が存在しない場合と friend-only により拒否された場合は,`PrivateMessageResult` の
    delivery
    status として返す. sender の silence,rate limit,content validation
    による拒否は`result=None`で返す.

    Attributes:
        _target_query (ResolvePrivateMessageTargetQuery):
            target existence と online state を解決する query.
        _friend_relationship_query (CheckFriendRelationshipQueryUseCase):
            friend-only target が sender を friend としているか確認する query.
        _command_service (CommandService):
            受理済み content に含まれる BanchoBot command を実行する service.
        _session_store (UserSessionLookup): sender と target の session state を検索する store.
        _persistence_publisher (ChatPersistenceWorkPublisher):
            受理済み private message の durable work を発行する port.
        _rate_limiter (RateLimiter): sender ごとの送信回数を制限する limiter.
        _config (AppConfig):
            message maximum length と既定 rate limit を提供する application configuration.
    """

    def __init__(
        self,
        *,
        target_query: ResolvePrivateMessageTargetQuery,
        friend_relationship_query: CheckFriendRelationshipQueryUseCase,
        command_service: CommandService,
        session_store: UserSessionLookup,
        persistence_publisher: ChatPersistenceWorkPublisher,
        rate_limiter: RateLimiter,
        config: AppConfig,
    ) -> None:
        """Private message workflow の query,state,publisher,rate-limit 依存関係を設定する.

        Args:
            target_query (ResolvePrivateMessageTargetQuery):
                target existence と online state を解決する query.
            friend_relationship_query (CheckFriendRelationshipQueryUseCase):
                target の friend-only setting を照合する query use-case.
            command_service (CommandService):
                受理済み content に対する BanchoBot command service.
            session_store (UserSessionLookup):
                sender と target の session state を取得する store.
            persistence_publisher (ChatPersistenceWorkPublisher):
                accepted message の durable work を発行する port.
            rate_limiter (RateLimiter): sender ごとの送信回数を制限する limiter.
            config (AppConfig):
                message maximum length と既定 rate limit を提供する configuration.

        """
        self._target_query: ResolvePrivateMessageTargetQuery = target_query
        self._friend_relationship_query: CheckFriendRelationshipQueryUseCase = (
            friend_relationship_query
        )
        self._command_service: CommandService = command_service
        self._session_store: UserSessionLookup = session_store
        self._persistence_publisher: ChatPersistenceWorkPublisher = persistence_publisher
        self._rate_limiter: RateLimiter = rate_limiter
        self._config: AppConfig = config

    async def execute(self, command: SendPrivateMessageCommand) -> SendPrivateMessageResult:
        """Private message を検証し,target status に応じた delivery result を作成する.

        Args:
            command (SendPrivateMessageCommand):
                sender,private target,authorization,content を含む command.

        Returns:
            SendPrivateMessageResult: target not found,friend-only blocked,online/offline
            delivery
            を表す結果. sender 側の silence,rate limit,validation 拒否では`result=None`.

        Notes:
            target が friend-only の場合は target が sender を friend としている必要がある.
            persistence work は
            target が存在し,friend-only policy を通過した場合だけ発行する.
        """
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
                    delivery_status=PrivateMessageDeliveryStatus.TARGET_NOT_FOUND,
                )
            )

        # Success guarantees target_id is not None.
        assert pm_result.target_id is not None
        target_id: int = pm_result.target_id
        target_session = await self._session_store.get_by_user(target_id)
        if target_session is not None and target_session.pm_private:
            target_added_sender = await self._friend_relationship_query.execute(
                owner_user_id=target_id,
                target_user_id=sender.user_id,
            )
            if not target_added_sender:
                return SendPrivateMessageResult(
                    result=PrivateMessageResult(
                        target_id=target_id,
                        is_online=True,
                        content=valid_content,
                        command_responses=command_responses,
                        delivery_status=PrivateMessageDeliveryStatus.BLOCKED_BY_FRIEND_ONLY,
                    )
                )

        await self._persistence_publisher.publish_private_message(
            PrivateMessagePersistenceWork(
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
            delivery_status=(
                PrivateMessageDeliveryStatus.DELIVERABLE
                if pm_result.is_online
                else PrivateMessageDeliveryStatus.OFFLINE
            ),
        )
        return SendPrivateMessageResult(result=result)

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
