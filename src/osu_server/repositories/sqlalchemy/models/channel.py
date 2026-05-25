from __future__ import annotations

from datetime import datetime  # noqa: TC003 — SQLAlchemy Mapped requires runtime import

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base


class ChannelModel(Base):
    __tablename__: str = "channels"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    topic: Mapped[str] = mapped_column(String(256), nullable=False, server_default="")
    channel_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default="public")
    read_privileges: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    write_privileges: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    manage_privileges: Mapped[int] = mapped_column(Integer, nullable=False, server_default="16")
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
