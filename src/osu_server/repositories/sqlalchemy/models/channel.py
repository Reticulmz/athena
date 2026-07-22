"""channelとmessage historyを保存するSQLAlchemy ORM modelを定義する.

channel accessのrole overrideとchannel/private messageは独立したtableで時系列順に検索する.
"""

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
    """stable channelの設定と公開範囲を表す.

    Attributes:
        __tablename__ (str): 保存先のchannels table名.
        id (Mapped[int]): 自動採番するchannelのprimary key.
        name (Mapped[str]): 一意なstable channel名.
        topic (Mapped[str]): channelに表示するtopic text.
        channel_type (Mapped[str]): public/privateなどのchannel種別.
        auto_join (Mapped[bool]): login時に自動joinさせるか.
        rate_limit_messages (Mapped[int | None]): window内に許可するmessage数. 未設定ならNULL.
        rate_limit_window (Mapped[int | None]): rate limit windowの秒数. 未設定ならNULL.
        created_at (Mapped[datetime]): channelを作成したUTC timestamp.
        updated_at (Mapped[datetime]): channel設定を最後に更新したUTC timestamp.
    """

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
    """channelごとにroleのread/write権限を上書きするrecordを表す.

    Attributes:
        __tablename__ (str): 保存先のchannel_role_overrides table名.
        channel_id (Mapped[int]): 対象channelのprimary keyかつforeign key.
        role_id (Mapped[int]): 権限を上書きするroleのprimary keyかつforeign key.
        can_read (Mapped[bool]): roleにchannel readを許可するか.
        can_write (Mapped[bool]): roleにchannel writeを許可するか.
    """

    __tablename__: str = "channel_role_overrides"

    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    can_read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    can_write: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class ChannelMessageModel(Base):
    """channelへ送信されたmessage historyを表す.

    Attributes:
        __tablename__ (str): 保存先のchannel_messages table名.
        __table_args__ (tuple[Index, ...]): channel内の時系列検索を支えるindex.
        id (Mapped[int]): 自動採番するmessageのprimary key.
        sender_id (Mapped[int]): messageを送信したuserのforeign key.
        channel_id (Mapped[int]): 送信先channelのforeign key.
        content (Mapped[str]): 保存するmessage body.
        created_at (Mapped[datetime]): messageを受信したUTC timestamp.
    """

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
    """user間で送信されたprivate message historyを表す.

    Attributes:
        __tablename__ (str): 保存先のprivate_messages table名.
        __table_args__ (tuple[Index, ...]): sender/target別の時系列検索を支えるindex群.
        id (Mapped[int]): 自動採番するprivate messageのprimary key.
        sender_id (Mapped[int]): messageを送信したuserのforeign key.
        target_user_id (Mapped[int]): messageを受信するuserのforeign key.
        content (Mapped[str]): 保存するmessage body.
        created_at (Mapped[datetime]): messageを受信したUTC timestamp.
    """

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
