"""score submissionとreplay attachmentを保存するSQLAlchemy ORM modelを定義する.

scoreは受理時のbeatmap eligibility snapshotを保持する.
submission idempotencyとreplay blobは別tableで参照する.
"""

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
    and_,
    column,
    func,
    or_,
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

_FAIL_TIME_MS_COLUMN = column("fail_time_ms", Integer)
_PLAY_TIME_SECONDS_COLUMN = column("play_time_seconds", Integer)
_REPLAY_VIEW_COUNT_COLUMN = column("replay_view_count", BigInteger)


class ScoreModel(Base):
    """stable clientから受理した1 playのimmutable score recordを表す.

    Attributes:
        __tablename__ (str): 保存先のscores table名.
        __table_args__ (tuple[CheckConstraint | Index, ...]):
            leaderboard検索と非負time/count制約のindex群.
        id (Mapped[int]): 自動採番するscoreのprimary key.
        user_id (Mapped[int]): scoreを提出したuserの識別子.
        beatmap_id (Mapped[int]): playしたbeatmapの識別子.
        beatmap_checksum (Mapped[str]): 提出時のbeatmap MD5 checksum.
        online_checksum (Mapped[str]): scoreを一意にするonline checksum.
        ruleset (Mapped[int]): 提出時のrulesetのcanonical integer値.
        playstyle (Mapped[int]): 提出時のplaystyleのcanonical integer値.
        mods (Mapped[int]): 提出時のraw mod bitflag.
        n300 (Mapped[int]): 300 judgement数.
        n100 (Mapped[int]): 100 judgement数.
        n50 (Mapped[int]): 50 judgement数.
        geki (Mapped[int]): geki judgement数.
        katu (Mapped[int]): katu judgement数.
        miss (Mapped[int]): miss judgement数.
        score (Mapped[int]): clientが報告したscore値.
        max_combo (Mapped[int]): 提出した最大combo.
        accuracy (Mapped[float]): judgementから計算したaccuracy ratio.
        grade (Mapped[str]): gradeのcanonical文字列値.
        passed (Mapped[bool]): beatmapをpassしたplayか.
        perfect (Mapped[bool]): full comboとして提出されたplayか.
        client_version (Mapped[str]): 提出元stable client version.
        submitted_at (Mapped[datetime]): scoreを受理したUTC timestamp.
        beatmap_status_at_submission (Mapped[str | None]): 提出時のrank status. 未確定ならNULL.
        leaderboard_eligible_at_submission (Mapped[bool]): 提出時にleaderboard対象だったか.
        fail_time_ms (Mapped[int | None]): failed playの失敗位置ms. pass時はNULL.
        play_time_seconds (Mapped[int | None]): play時間秒数. 不明ならNULL.
        play_time_source (Mapped[str | None]): play_time_secondsの取得source. 不明ならNULL.
        submit_exit_classification (Mapped[str | None]): submission処理の終了分類. 未分類ならNULL.
        replay_view_count (Mapped[int]): replay downloadの観測回数. 負値は保存できない.
    """

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
    """score submissionのidempotency fingerprintと処理結果を表す.

    Attributes:
        __tablename__ (str): 保存先のscore_submissions table名.
        __table_args__ (tuple[Index, ...]): userと受理時刻の検索を支えるindex群.
        id (Mapped[int]): 自動採番するsubmissionのprimary key.
        fingerprint (Mapped[str]): 同一submissionを識別する一意なSHA-256 fingerprint.
        user_id (Mapped[int]): submissionを開始したuserの識別子.
        beatmap_checksum (Mapped[str]): submission対象beatmapのMD5 checksum.
        submitted_at (Mapped[datetime]): submissionを受理したUTC timestamp.
        state (Mapped[str]): processing/completedなどのsubmission lifecycle状態.
        result_snapshot (Mapped[dict[str, Any] | None]):
            retry時に再利用するopaque JSONB結果. 未完了ならNULL.
    """

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
    """scoreに添付されたreplay file blobを表す.

    Attributes:
        __tablename__ (str): 保存先のreplay_file_attachments table名.
        __table_args__ (tuple[Index, ...]): score/blob lookupを支えるindex群.
        id (Mapped[int]): 自動採番するreplay attachmentのprimary key.
        score_id (Mapped[int]): replayを持つscoreのforeign key.
        blob_id (Mapped[int]): replay contentを持つblobのforeign key.
        checksum_sha256 (Mapped[str]): replay contentの一意なSHA-256 checksum.
        byte_size (Mapped[int]): replay contentのbyte数.
        created_at (Mapped[datetime]): attachmentを作成したUTC timestamp.
    """

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
