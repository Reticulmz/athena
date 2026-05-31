"""SQLAlchemyChatRepository — async database-backed chat history repository."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Protocol

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
    from sqlalchemy.sql.base import Executable


class _ChannelIdResult(Protocol):
    def scalar_one_or_none(self) -> int | None: ...


class _ChatPersistenceSession(Protocol):
    def execute(self, statement: Executable) -> Awaitable[_ChannelIdResult]: ...

    def add(self, instance: object) -> None: ...

    def commit(self) -> Awaitable[None]: ...


type _ChatSessionFactory = Callable[
    [],
    AbstractAsyncContextManager[_ChatPersistenceSession],
]


class SQLAlchemyChatRepository:
    """SQLAlchemy implementation of the ChatRepository Protocol."""

    _session_factory: _ChatSessionFactory

    def __init__(self, session_factory: _ChatSessionFactory) -> None:
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
    async def _resolve_channel_id(
        session: _ChatPersistenceSession,
        channel_name: str,
    ) -> int | None:
        """Return channel id for *channel_name*, or ``None`` if unresolved."""
        stmt = select(ChannelModel.id).where(ChannelModel.name == channel_name)
        return (await session.execute(stmt)).scalar_one_or_none()
