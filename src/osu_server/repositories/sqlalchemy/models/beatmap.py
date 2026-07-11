from __future__ import annotations

from datetime import datetime  # noqa: TC003 -- SQLAlchemy Mapped requires runtime import
from decimal import Decimal  # noqa: TC003 -- SQLAlchemy Mapped requires runtime import

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    column,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models.enum_types import (
    BEATMAP_FETCH_STATE_ENUM,
    BEATMAP_FETCH_TARGET_KIND_ENUM,
    BEATMAP_FILE_SOURCE_ENUM,
    BEATMAP_METADATA_SOURCE_ENUM,
    BEATMAP_MODE_ENUM,
    BEATMAP_RANK_STATUS_ENUM,
    LOCAL_BEATMAP_STATUS_ENUM,
)

_PLAY_COUNT_COLUMN = column("play_count", BigInteger)
_PASS_COUNT_COLUMN = column("pass_count", BigInteger)


class BeatmapSetModel(Base):
    __tablename__: str = "beatmapsets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    artist: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    creator: Mapped[str] = mapped_column(String(255), nullable=False)
    artist_unicode: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title_unicode: Mapped[str | None] = mapped_column(String(255), nullable=True)
    official_status: Mapped[str] = mapped_column(BEATMAP_RANK_STATUS_ENUM, nullable=False)
    official_status_source: Mapped[str] = mapped_column(
        BEATMAP_METADATA_SOURCE_ENUM,
        nullable=False,
    )
    official_status_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_refresh_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class BeatmapModel(Base):
    __tablename__: str = "beatmaps"
    __table_args__: tuple[UniqueConstraint | Index | CheckConstraint, ...] = (
        UniqueConstraint("checksum_md5", name="uq_beatmaps_checksum_md5"),
        CheckConstraint(_PLAY_COUNT_COLUMN >= 0, name="ck_beatmaps_play_count_non_negative"),
        CheckConstraint(_PASS_COUNT_COLUMN >= 0, name="ck_beatmaps_pass_count_non_negative"),
        CheckConstraint(
            _PASS_COUNT_COLUMN <= _PLAY_COUNT_COLUMN,
            name="ck_beatmaps_pass_count_lte_play_count",
        ),
        Index("idx_beatmaps_beatmapset_id", "beatmapset_id"),
        Index("idx_beatmaps_checksum_md5", "checksum_md5"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    beatmapset_id: Mapped[int] = mapped_column(
        ForeignKey("beatmapsets.id", name="fk_beatmaps_beatmapset_id"), nullable=False
    )
    checksum_md5: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mode: Mapped[str] = mapped_column(BEATMAP_MODE_ENUM, nullable=False)
    version: Mapped[str] = mapped_column(String(255), nullable=False)
    total_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hit_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_combo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bpm: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    cs: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    od: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    ar: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    hp: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    difficulty_rating: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    official_status: Mapped[str] = mapped_column(BEATMAP_RANK_STATUS_ENUM, nullable=False)
    official_status_source: Mapped[str] = mapped_column(
        BEATMAP_METADATA_SOURCE_ENUM,
        nullable=False,
    )
    official_status_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    local_status_override: Mapped[str | None] = mapped_column(
        LOCAL_BEATMAP_STATUS_ENUM,
        nullable=True,
    )
    local_status_override_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    play_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    pass_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    official_last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_refresh_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class BeatmapFileAttachmentModel(Base):
    __tablename__: str = "beatmap_file_attachments"
    __table_args__: tuple[UniqueConstraint | Index, ...] = (
        UniqueConstraint(
            "beatmap_id",
            "checksum_md5",
            name="uq_beatmap_file_attachments_beatmap_checksum_md5",
        ),
        Index("idx_beatmap_file_attachments_beatmap", "beatmap_id"),
        Index("idx_beatmap_file_attachments_blob", "blob_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    beatmap_id: Mapped[int] = mapped_column(
        ForeignKey("beatmaps.id", name="fk_beatmap_file_attachments_beatmap_id"), nullable=False
    )
    blob_id: Mapped[int] = mapped_column(
        ForeignKey("blobs.id", name="fk_beatmap_file_attachments_blob_id"), nullable=False
    )
    checksum_md5: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_md5: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(BEATMAP_FILE_SOURCE_ENUM, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BeatmapFetchStateModel(Base):
    __tablename__: str = "beatmap_fetch_states"
    __table_args__: tuple[UniqueConstraint | Index, ...] = (
        UniqueConstraint("target_type", "target_key", name="uq_beatmap_fetch_states_target"),
        Index("idx_beatmap_fetch_states_target_lookup", "target_type", "target_key", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(BEATMAP_FETCH_TARGET_KIND_ENUM, nullable=False)
    target_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(BEATMAP_FETCH_STATE_ENUM, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
