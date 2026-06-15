"""SQLAlchemy command-side chat repository."""

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
    """Chat command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def save_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        """Persist accepted public channel chat history."""
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
        """Persist accepted private chat history."""
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
        stmt = select(ChannelModel.id).where(ChannelModel.name == channel_name)
        return (await self._session.execute(stmt)).scalar_one_or_none()
