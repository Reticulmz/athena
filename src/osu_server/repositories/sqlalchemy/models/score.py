from __future__ import annotations

from datetime import datetime  # noqa: TC003 — SQLAlchemy Mapped requires runtime import
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base


class ScoreModel(Base):
    __tablename__: str = "scores"
    __table_args__: tuple[Index, ...] = (
        Index("idx_scores_user_id", "user_id"),
        Index("idx_scores_beatmap_id", "beatmap_id"),
        Index("idx_scores_submitted_at", "submitted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    beatmap_id: Mapped[int] = mapped_column(Integer, nullable=False)
    beatmap_checksum: Mapped[str] = mapped_column(String(32), nullable=False)
    online_checksum: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    ruleset: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    playstyle: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    mods: Mapped[int] = mapped_column(Integer, nullable=False)
    n300: Mapped[int] = mapped_column(Integer, nullable=False)
    n100: Mapped[int] = mapped_column(Integer, nullable=False)
    n50: Mapped[int] = mapped_column(Integer, nullable=False)
    geki: Mapped[int] = mapped_column(Integer, nullable=False)
    katu: Mapped[int] = mapped_column(Integer, nullable=False)
    miss: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    max_combo: Mapped[int] = mapped_column(Integer, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    grade: Mapped[str] = mapped_column(String(2), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    perfect: Mapped[bool] = mapped_column(Boolean, nullable=False)
    client_version: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    beatmap_status_at_submission: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ScoreSubmissionModel(Base):
    __tablename__: str = "score_submissions"
    __table_args__: tuple[Index, ...] = (
        Index("idx_submissions_user_id", "user_id"),
        Index("idx_submissions_submitted_at", "submitted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    beatmap_checksum: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    result_snapshot: Mapped[dict[str, Any] | None] = mapped_column(  # pyright: ignore[reportExplicitAny] — opaque JSONB field
        JSONB, nullable=True
    )


class ReplayModel(Base):
    __tablename__: str = "replay_file_attachments"
    __table_args__: tuple[Index, ...] = (
        Index("idx_replay_file_attachments_score_id", "score_id"),
        Index("idx_replay_file_attachments_blob_id", "blob_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    score_id: Mapped[int] = mapped_column(
        ForeignKey("scores.id", name="fk_replay_file_attachments_score_id"), nullable=False
    )
    blob_id: Mapped[int] = mapped_column(
        ForeignKey("blobs.id", name="fk_replay_file_attachments_blob_id"), nullable=False
    )
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
