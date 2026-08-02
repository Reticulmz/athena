"""SQLAlchemyでchannel messageとprivate messageを保存するrepositoryを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog.stdlib
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from osu_server.domain.chat import (
    ChatPersistenceFailureReason,
    ChatPersistenceResult,
)
from osu_server.repositories.sqlalchemy.commands.error_details import sqlalchemy_error_details
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelMessageModel,
    ChannelModel,
    PrivateMessageModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(__name__)


class SQLAlchemyChatCommandRepository:
    """Unit of Work所有sessionで受理済みchat履歴を保存するrepository.

    Attributes:
        _session (AsyncSession): command transactionを実行しcommitを所有しないsession.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Workから受け取ったSQLAlchemy sessionを保持する.

        Args:
            session (AsyncSession): chat履歴の保存に使うsession.

        Notes:
            commitとrollbackは呼び出し側のUnit of Workが所有する.
        """
        self._session: AsyncSession = session

    async def save_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        """受理済みchannel messageを保存し結果を返す.

        Args:
            sender_id (int): messageを送信したuserの永続化識別子.
            channel_name (str): 保存先channelの完全一致name.
            content (str): 保存するmessage本文.

        Returns:
            ChatPersistenceResult: 成功またはchannel未存在とstorage errorを表す結果.

        Notes:
            SQLAlchemyErrorはlogへ記録し例外ではなくSTORAGE_ERROR結果に変換する.
        """
        try:
            channel_id = await self._resolve_channel_id(channel_name)
            if channel_id is None:
                return ChatPersistenceResult.failure(
                    ChatPersistenceFailureReason.CHANNEL_NOT_FOUND
                )

            self._session.add(
                ChannelMessageModel(
                    sender_id=sender_id,
                    channel_id=channel_id,
                    content=content,
                )
            )
            await self._session.flush()
        except SQLAlchemyError as exc:
            logger.exception(
                "chat_persistence_storage_error",
                operation="save_channel_message",
                sender_id=sender_id,
                channel_name=channel_name,
                reason=ChatPersistenceFailureReason.STORAGE_ERROR.value,
                **sqlalchemy_error_details(exc),
            )
            return ChatPersistenceResult.failure(ChatPersistenceFailureReason.STORAGE_ERROR)

        return ChatPersistenceResult.success_result()

    async def save_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult:
        """受理済みprivate messageを保存し結果を返す.

        Args:
            sender_id (int): messageを送信したuserの永続化識別子.
            target_id (int): messageを受信するuserの永続化識別子.
            content (str): 保存するmessage本文.

        Returns:
            ChatPersistenceResult: 成功またはstorage errorを表す結果.

        Notes:
            SQLAlchemyErrorはlogへ記録し例外ではなくSTORAGE_ERROR結果に変換する.
        """
        try:
            self._session.add(
                PrivateMessageModel(
                    sender_id=sender_id,
                    target_user_id=target_id,
                    content=content,
                )
            )
            await self._session.flush()
        except SQLAlchemyError as exc:
            logger.exception(
                "chat_persistence_storage_error",
                operation="save_private_message",
                sender_id=sender_id,
                target_id=target_id,
                reason=ChatPersistenceFailureReason.STORAGE_ERROR.value,
                **sqlalchemy_error_details(exc),
            )
            return ChatPersistenceResult.failure(ChatPersistenceFailureReason.STORAGE_ERROR)

        return ChatPersistenceResult.success_result()

    async def _resolve_channel_id(self, channel_name: str) -> int | None:
        """Channel nameからmessage保存用の永続化idを解決する.

        Args:
            channel_name (str): 解決対象channelの完全一致name.

        Returns:
            int | None: 対応するchannel id. 存在しない場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        stmt = select(ChannelModel.id).where(ChannelModel.name == channel_name)
        return (await self._session.execute(stmt)).scalar_one_or_none()
