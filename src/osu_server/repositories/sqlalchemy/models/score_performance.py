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
    and_,
    column,
    func,
    or_,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models.enum_types import (
    FORMULA_PROFILE_ENUM,
    PERFORMANCE_CALCULATION_STATE_ENUM,
    PERFORMANCE_RECALCULATION_BATCH_STATUS_ENUM,
    PERFORMANCE_RECALCULATION_REASON_ENUM,
    PERFORMANCE_RECALCULATION_WORK_ITEM_STATE_ENUM,
)

_CALCULATION_STATE_COLUMN = column("state", PERFORMANCE_CALCULATION_STATE_ENUM)
_CALCULATION_PP_COLUMN = column("pp", Numeric(12, 6))
_CALCULATION_STAR_RATING_COLUMN = column("star_rating", Numeric(8, 5))
_CALCULATION_CALCULATED_AT_COLUMN = column("calculated_at", DateTime(timezone=True))
_CALCULATION_UNAVAILABLE_REASON_COLUMN = column("unavailable_reason", String(128))
_CALCULATION_CLAIM_OWNER_COLUMN = column("claim_owner", String(128))
_CALCULATION_CLAIM_EXPIRES_AT_COLUMN = column("claim_expires_at", DateTime(timezone=True))
_CALCULATION_IS_CURRENT_COLUMN = column("is_current", Boolean)
_COMPLETED_VALUES_CONSTRAINT = or_(
    _CALCULATION_STATE_COLUMN != "completed",
    and_(
        _CALCULATION_PP_COLUMN.is_not(None),
        _CALCULATION_STAR_RATING_COLUMN.is_not(None),
        _CALCULATION_CALCULATED_AT_COLUMN.is_not(None),
    ),
)
_UNAVAILABLE_REASON_CONSTRAINT = or_(
    _CALCULATION_STATE_COLUMN != "unavailable",
    _CALCULATION_UNAVAILABLE_REASON_COLUMN.is_not(None),
)
_CALCULATION_CLAIM_METADATA_PAIR = or_(
    and_(
        _CALCULATION_CLAIM_OWNER_COLUMN.is_(None),
        _CALCULATION_CLAIM_EXPIRES_AT_COLUMN.is_(None),
    ),
    and_(
        _CALCULATION_CLAIM_OWNER_COLUMN.is_not(None),
        _CALCULATION_CLAIM_EXPIRES_AT_COLUMN.is_not(None),
    ),
)
_CALCULATION_CLAIM_METADATA_CONSTRAINT = and_(
    _CALCULATION_CLAIM_METADATA_PAIR,
    or_(
        _CALCULATION_STATE_COLUMN.in_(("queued", "fetching_file", "calculating")),
        and_(
            _CALCULATION_CLAIM_OWNER_COLUMN.is_(None),
            _CALCULATION_CLAIM_EXPIRES_AT_COLUMN.is_(None),
        ),
    ),
)
_WORK_ITEM_STATE_COLUMN = column("state", PERFORMANCE_RECALCULATION_WORK_ITEM_STATE_ENUM)
_WORK_ITEM_CLAIM_OWNER_COLUMN = column("claim_owner", String(128))
_WORK_ITEM_CLAIM_EXPIRES_AT_COLUMN = column("claim_expires_at", DateTime(timezone=True))
_WORK_ITEM_CLAIM_METADATA_CONSTRAINT = or_(
    and_(
        _WORK_ITEM_STATE_COLUMN == "claimed",
        _WORK_ITEM_CLAIM_OWNER_COLUMN.is_not(None),
        _WORK_ITEM_CLAIM_EXPIRES_AT_COLUMN.is_not(None),
    ),
    and_(
        _WORK_ITEM_STATE_COLUMN != "claimed",
        _WORK_ITEM_CLAIM_OWNER_COLUMN.is_(None),
        _WORK_ITEM_CLAIM_EXPIRES_AT_COLUMN.is_(None),
    ),
)


class ScorePerformanceCalculationModel(Base):
    """1回の PP 計算と処理中の lease を保持する ORM model.

    `claim_owner` は処理中 worker の識別子、`claim_expires_at` は lease 有効期限を表す.
    未 claim または terminal state では両方を `NULL` にし、片方だけの保存を禁止する.
    """

    __tablename__: str = "score_performance_calculations"
    __table_args__: tuple[CheckConstraint | Index, ...] = (
        CheckConstraint(
            _COMPLETED_VALUES_CONSTRAINT,
            name="ck_score_performance_completed_values",
        ),
        CheckConstraint(
            _UNAVAILABLE_REASON_CONSTRAINT,
            name="ck_score_performance_unavailable_reason",
        ),
        CheckConstraint(
            _CALCULATION_CLAIM_METADATA_CONSTRAINT,
            name="ck_score_performance_claim_metadata_pair",
        ),
        Index(
            "idx_score_performance_current_unique",
            "score_id",
            unique=True,
            postgresql_where=_CALCULATION_IS_CURRENT_COLUMN.is_(True),
        ),
        Index("idx_score_performance_score_current", "score_id", "is_current"),
        Index("idx_score_performance_state_claim", "state", "claim_expires_at"),
        Index("idx_score_performance_provenance", "calculator_version", "formula_profile"),
        Index("idx_score_performance_file_attachment", "beatmap_file_attachment_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    score_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("scores.id", name="fk_score_performance_calculations_score_id"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(PERFORMANCE_CALCULATION_STATE_ENUM, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pp: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    star_rating: Mapped[Decimal | None] = mapped_column(Numeric(8, 5), nullable=True)
    calculator_name: Mapped[str] = mapped_column(String(64), nullable=False)
    calculator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    formula_profile: Mapped[str] = mapped_column(FORMULA_PROFILE_ENUM, nullable=False)
    beatmap_file_attachment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "beatmap_file_attachments.id",
            name="fk_score_performance_calculations_beatmap_file_attachment_id",
        ),
        nullable=True,
    )
    beatmap_file_checksum_md5: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unavailable_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claim_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PerformanceRecalculationBatchModel(Base):
    __tablename__: str = "performance_recalculation_batches"
    __table_args__: tuple[Index, ...] = (
        Index("idx_performance_recalculation_batches_status", "status"),
        Index("idx_performance_recalculation_batches_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(
        PERFORMANCE_RECALCULATION_BATCH_STATUS_ENUM,
        nullable=False,
    )
    filters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    reason_counts: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    target_calculator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    target_formula_profile: Mapped[str] = mapped_column(FORMULA_PROFILE_ENUM, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unavailable_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PerformanceRecalculationWorkItemModel(Base):
    """再計算 batch 内の1 score と worker claim を保持する ORM model.

    `CLAIMED` state だけが `claim_owner` と `claim_expires_at` を持つ. `PENDING` と
    terminal state では両方を `NULL` にする.
    """

    __tablename__: str = "performance_recalculation_work_items"
    __table_args__: tuple[CheckConstraint | Index, ...] = (
        CheckConstraint(
            _WORK_ITEM_CLAIM_METADATA_CONSTRAINT,
            name="ck_performance_recalculation_work_item_claim_metadata",
        ),
        Index("idx_performance_recalculation_work_items_batch_state", "batch_id", "state"),
        Index(
            "idx_performance_recalculation_work_items_state_claim",
            "state",
            "claim_expires_at",
        ),
        Index("idx_performance_recalculation_work_items_score_reason", "score_id", "reason"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "performance_recalculation_batches.id",
            name="fk_performance_recalculation_work_items_batch_id",
        ),
        nullable=False,
    )
    score_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("scores.id", name="fk_performance_recalculation_work_items_score_id"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(PERFORMANCE_RECALCULATION_REASON_ENUM, nullable=False)
    state: Mapped[str] = mapped_column(
        PERFORMANCE_RECALCULATION_WORK_ITEM_STATE_ENUM,
        nullable=False,
    )
    calculation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "score_performance_calculations.id",
            name="fk_performance_recalculation_work_items_calculation_id",
        ),
        nullable=True,
    )
    claim_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
