from __future__ import annotations

from datetime import datetime  # noqa: TC003 — SQLAlchemy Mapped requires runtime import

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models.enum_types import CHANNEL_TYPE_ENUM


class ChannelModel(Base):
    __tablename__: str = "channels"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    topic: Mapped[str] = mapped_column(String(256), nullable=False, server_default="")
    channel_type: Mapped[str] = mapped_column(
        CHANNEL_TYPE_ENUM,
        nullable=False,
        server_default="public",
    )
    auto_join: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    rate_limit_messages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ChannelRoleOverrideModel(Base):
    __tablename__: str = "channel_role_overrides"

    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    can_read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    can_write: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class ChannelMessageModel(Base):
    __tablename__: str = "channel_messages"
    __table_args__: tuple[Index, ...] = (
        Index("idx_channel_messages_channel_created", "channel_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PrivateMessageModel(Base):
    __tablename__: str = "private_messages"
    __table_args__: tuple[Index, ...] = (
        Index("idx_private_messages_target_created", "target_user_id", "created_at"),
        Index("idx_private_messages_sender_created", "sender_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    target_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
