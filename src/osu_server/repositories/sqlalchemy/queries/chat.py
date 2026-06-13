"""SQLAlchemy query-side chat history repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import or_, select

from osu_server.repositories.interfaces.queries import ChatHistoryMessage
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelMessageModel,
    ChannelModel,
    PrivateMessageModel,
)

if TYPE_CHECKING:
    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory


class SQLAlchemyChatHistoryQueryRepository:
    """Read-only chat history repository backed by short SQLAlchemy sessions."""

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        self._session_factory = session_factory

    async def list_channel_messages(
        self,
        channel_name: str,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[ChatHistoryMessage]:
        async with self._session_factory() as session:
            stmt = (
                select(ChannelMessageModel)
                .join(ChannelModel, ChannelModel.id == ChannelMessageModel.channel_id)
                .where(ChannelModel.name == channel_name)
                .order_by(ChannelMessageModel.created_at.desc(), ChannelMessageModel.id.desc())
                .limit(limit)
            )
            if before_message_id is not None:
                stmt = stmt.where(ChannelMessageModel.id < before_message_id)
            models = (await session.execute(stmt)).scalars().all()
            return [_channel_message_to_read_model(model) for model in models]

    async def list_private_messages(
        self,
        user_id: int,
        peer_user_id: int,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[ChatHistoryMessage]:
        async with self._session_factory() as session:
            stmt = (
                select(PrivateMessageModel)
                .where(
                    or_(
                        PrivateMessageModel.sender_id == user_id,
                        PrivateMessageModel.sender_id == peer_user_id,
                    ),
                    or_(
                        PrivateMessageModel.target_user_id == user_id,
                        PrivateMessageModel.target_user_id == peer_user_id,
                    ),
                )
                .order_by(PrivateMessageModel.created_at.desc(), PrivateMessageModel.id.desc())
                .limit(limit)
            )
            if before_message_id is not None:
                stmt = stmt.where(PrivateMessageModel.id < before_message_id)
            models = (await session.execute(stmt)).scalars().all()
            return [_private_message_to_read_model(model) for model in models]


def _channel_message_to_read_model(model: ChannelMessageModel) -> ChatHistoryMessage:
    return ChatHistoryMessage(
        id=model.id,
        sender_id=model.sender_id,
        content=model.content,
        created_at=model.created_at,
    )


def _private_message_to_read_model(model: PrivateMessageModel) -> ChatHistoryMessage:
    return ChatHistoryMessage(
        id=model.id,
        sender_id=model.sender_id,
        content=model.content,
        created_at=model.created_at,
    )
