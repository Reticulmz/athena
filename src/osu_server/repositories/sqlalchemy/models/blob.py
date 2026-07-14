from __future__ import annotations

from datetime import datetime  # noqa: TC003 — SQLAlchemy Mapped requires runtime import

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    String,
    UniqueConstraint,
    column,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models.enum_types import BLOB_STORAGE_BACKEND_ENUM

_BYTE_SIZE_COLUMN = column("byte_size", BigInteger)


class BlobModel(Base):
    __tablename__: str = "blobs"
    __table_args__: tuple[UniqueConstraint, CheckConstraint] = (
        UniqueConstraint("sha256", name="uq_blobs_sha256"),
        CheckConstraint(_BYTE_SIZE_COLUMN >= 0, name="ck_blobs_byte_size_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_backend: Mapped[str] = mapped_column(BLOB_STORAGE_BACKEND_ENUM, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
