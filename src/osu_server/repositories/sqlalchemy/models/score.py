from __future__ import annotations

from datetime import datetime  # noqa: TC003 — SQLAlchemy Mapped requires runtime import
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    and_,
    case,
    column,
    func,
    or_,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, array
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.domain.scores.mods import Mod
from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models.enum_types import (
    BEATMAP_RANK_STATUS_ENUM,
    PLAY_TIME_SOURCE_ENUM,
    SCORE_GRADE_ENUM,
    SCORE_SUBMISSION_STATE_ENUM,
)

_NIGHTCORE_BIT = int(Mod.NIGHTCORE)
_DOUBLE_TIME_BIT = int(Mod.DOUBLE_TIME)
_PERFECT_BIT = int(Mod.PERFECT)
_SUDDEN_DEATH_BIT = int(Mod.SUDDEN_DEATH)
_MIRROR_BIT = int(Mod.MIRROR)
_PREFERENCE_ONLY_NO_MODS_BITS = int(Mod.SUDDEN_DEATH | Mod.PERFECT | Mod.MIRROR)
_MODS_COLUMN = column("mods", Integer)
_NIGHTCORE_NORMALIZED_MODS = case(
    (
        _MODS_COLUMN.bitwise_and(_NIGHTCORE_BIT) != 0,
        _MODS_COLUMN.bitwise_or(_DOUBLE_TIME_BIT).bitwise_and(~_NIGHTCORE_BIT),
    ),
    else_=_MODS_COLUMN,
)
_PERFECT_NORMALIZED_MODS = case(
    (
        _NIGHTCORE_NORMALIZED_MODS.bitwise_and(_PERFECT_BIT) != 0,
        _NIGHTCORE_NORMALIZED_MODS.bitwise_or(_SUDDEN_DEATH_BIT).bitwise_and(~_PERFECT_BIT),
    ),
    else_=_NIGHTCORE_NORMALIZED_MODS,
)
_CANONICAL_MODS = _PERFECT_NORMALIZED_MODS.bitwise_and(~_MIRROR_BIT)
_IS_NO_MOD_CANDIDATE = _CANONICAL_MODS.bitwise_and(~_PREFERENCE_ONLY_NO_MODS_BITS) == 0
_LEADERBOARD_MOD_FILTER_KEYS = case(
    (
        and_(_IS_NO_MOD_CANDIDATE, _CANONICAL_MODS == 0),
        array([0]),
    ),
    (
        _IS_NO_MOD_CANDIDATE,
        array([0, _CANONICAL_MODS]),
    ),
    else_=array([_CANONICAL_MODS]),
)
_FAIL_TIME_MS_COLUMN = column("fail_time_ms", Integer)
_PLAY_TIME_SECONDS_COLUMN = column("play_time_seconds", Integer)
_REPLAY_VIEW_COUNT_COLUMN = column("replay_view_count", BigInteger)


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
        Index(
            "idx_scores_beatmap_leaderboard_candidates",
            "beatmap_id",
            "ruleset",
            "playstyle",
            "beatmap_checksum",
            "user_id",
            column("score", Integer).desc(),
            column("submitted_at", DateTime(timezone=True)).asc(),
            column("id", BigInteger).asc(),
            postgresql_where=and_(
                column("passed", Boolean).is_(True),
                column("leaderboard_eligible_at_submission", Boolean).is_(True),
            ),
        ),
        Index(
            "idx_scores_leaderboard_mod_filter_keys",
            "leaderboard_mod_filter_keys",
            postgresql_using="gin",
        ),
        CheckConstraint(
            or_(_FAIL_TIME_MS_COLUMN.is_(None), _FAIL_TIME_MS_COLUMN >= 0),
            name="ck_scores_fail_time_ms_non_negative",
        ),
        CheckConstraint(
            or_(_PLAY_TIME_SECONDS_COLUMN.is_(None), _PLAY_TIME_SECONDS_COLUMN >= 0),
            name="ck_scores_play_time_seconds_non_negative",
        ),
        CheckConstraint(
            _REPLAY_VIEW_COUNT_COLUMN >= 0,
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
    leaderboard_mod_filter_keys: Mapped[list[int]] = mapped_column(
        ARRAY(Integer),
        Computed(_LEADERBOARD_MOD_FILTER_KEYS, persisted=True),
        nullable=False,
    )
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
