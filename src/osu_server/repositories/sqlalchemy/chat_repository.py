"""SQLAlchemyChatRepository — async database-backed chat history repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from osu_server.repositories.interfaces.chat_repository import (
    ChatPersistenceFailureReason,
    ChatPersistenceResult,
)
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelMessageModel,
    ChannelModel,
    PrivateMessageModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SQLAlchemyChatRepository:
    """SQLAlchemy implementation of the ChatRepository Protocol."""

    _session_factory: async_sessionmaker[AsyncSession]

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        """Persist accepted public channel chat history."""
        try:
            async with self._session_factory() as session:
                channel_id = await self._resolve_channel_id(session, channel_name)
                if channel_id is None:
                    return ChatPersistenceResult.failure(
                        ChatPersistenceFailureReason.CHANNEL_NOT_FOUND
                    )

                session.add(
                    ChannelMessageModel(
                        sender_id=sender_id,
                        channel_id=channel_id,
                        content=content,
                    )
                )
                await session.commit()
        except SQLAlchemyError:
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
            async with self._session_factory() as session:
                session.add(
                    PrivateMessageModel(
                        sender_id=sender_id,
                        target_user_id=target_id,
                        content=content,
                    )
                )
                await session.commit()
        except SQLAlchemyError:
            return ChatPersistenceResult.failure(ChatPersistenceFailureReason.STORAGE_ERROR)

        return ChatPersistenceResult.success_result()

    @staticmethod
    async def _resolve_channel_id(session: AsyncSession, channel_name: str) -> int | None:
        """Return channel id for *channel_name*, or ``None`` if unresolved."""
        stmt = select(ChannelModel.id).where(ChannelModel.name == channel_name)
        return (await session.execute(stmt)).scalar_one_or_none()
