from __future__ import annotations

from datetime import datetime  # noqa: TC003 — SQLAlchemy Mapped requires runtime import
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models.enum_types import (
    BEATMAP_RANK_STATUS_ENUM,
    PLAY_TIME_SOURCE_ENUM,
    SCORE_GRADE_ENUM,
    SCORE_SUBMISSION_STATE_ENUM,
)


class ScoreModel(Base):
    __tablename__: str = "scores"
    __table_args__: tuple[CheckConstraint | Index, ...] = (
        Index("idx_scores_user_id", "user_id"),
        Index("idx_scores_beatmap_id", "beatmap_id"),
        Index("idx_scores_submitted_at", "submitted_at"),
        Index(
            "idx_scores_leaderboard_rebuild_candidate",
            "beatmap_id",
            "ruleset",
            "playstyle",
            "user_id",
            "leaderboard_eligible_at_submission",
            "passed",
            "score",
            "submitted_at",
            "id",
        ),
        CheckConstraint(
            "fail_time_ms IS NULL OR fail_time_ms >= 0",
            name="ck_scores_fail_time_ms_non_negative",
        ),
        CheckConstraint(
            "play_time_seconds IS NULL OR play_time_seconds >= 0",
            name="ck_scores_play_time_seconds_non_negative",
        ),
        CheckConstraint(
            "replay_view_count >= 0",
            name="ck_scores_replay_view_count_non_negative",
        ),
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
    grade: Mapped[str] = mapped_column(SCORE_GRADE_ENUM, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    perfect: Mapped[bool] = mapped_column(Boolean, nullable=False)
    client_version: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    beatmap_status_at_submission: Mapped[str | None] = mapped_column(
        BEATMAP_RANK_STATUS_ENUM, nullable=True
    )
    leaderboard_eligible_at_submission: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    fail_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    play_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    play_time_source: Mapped[str | None] = mapped_column(PLAY_TIME_SOURCE_ENUM, nullable=True)
    submit_exit_classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    replay_view_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )


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
    state: Mapped[str] = mapped_column(SCORE_SUBMISSION_STATE_ENUM, nullable=False)
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
