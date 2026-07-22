"""score performance計算とrecalculation queueを保存するORM modelを定義する.

calculationとbatch work itemはlease metadataをdatabase constraintで検証する.
worker間の状態遷移を保護する.
"""

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
    """1回のperformance calculationと処理中leaseを保存する.

    Attributes:
        __tablename__ (str): 保存先のscore_performance_calculations table名.
        __table_args__ (tuple[CheckConstraint | Index, ...]):
            lifecycle値とlease整合性およびlookup index.
        id (Mapped[int]): 自動採番するcalculationのprimary key.
        score_id (Mapped[int]): 計算対象scoreのforeign key.
        state (Mapped[str]): queued/completed/unavailableなどのcalculation状態.
        is_current (Mapped[bool]): scoreのcurrent calculationとして採用するか.
        pp (Mapped[Decimal | None]): 算出したperformance point. 未完了ならNULL.
        star_rating (Mapped[Decimal | None]): 算出したstar rating. 未完了ならNULL.
        calculator_name (Mapped[str]): 結果を算出したcalculator名.
        calculator_version (Mapped[str]): 結果を算出したcalculator version.
        formula_profile (Mapped[str]): 使用したformula profile.
        beatmap_file_attachment_id (Mapped[int | None]): 計算入力.osu file attachmentのforeign key.
        beatmap_file_checksum_md5 (Mapped[str | None]): 計算入力fileのMD5 checksum.
        unavailable_reason (Mapped[str | None]): unavailable状態の理由. 他状態ではNULLを許可する.
        claim_owner (Mapped[str | None]): 現在処理するworkerの識別子. 未claimならNULL.
        claim_expires_at (Mapped[datetime | None]):
            現claimのlease失効UTC timestamp. 未claimならNULL.
        attempt_count (Mapped[int]): queueからclaimした試行回数.
        created_at (Mapped[datetime]): calculationを作成したUTC timestamp.
        updated_at (Mapped[datetime]): calculationを最後に更新したUTC timestamp.
        calculated_at (Mapped[datetime | None]): 結果を計算したUTC timestamp. 未完了ならNULL.

    Notes:
        completed状態はpp/star_rating/calculated_atを必須にする.
        unavailable状態はunavailable_reasonを必須にする.
        claim_ownerとclaim_expires_atは常に両方NULLまたは両方非NULLである.
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
    """performance再計算の対象集合と集計進捗を保存する.

    Attributes:
        __tablename__ (str): 保存先のperformance_recalculation_batches table名.
        __table_args__ (tuple[Index, ...]): statusと作成時刻の検索を支えるindex群.
        id (Mapped[int]): 自動採番するrecalculation batchのprimary key.
        status (Mapped[str]): queued/running/completedなどのbatch lifecycle状態.
        filters (Mapped[dict[str, object]]): 対象scoreを選択したfilter snapshotのJSONB.
        reason_counts (Mapped[dict[str, object]]): 再計算理由別のcandidate数JSONB.
        target_calculator_version (Mapped[str]): 再計算で使うcalculator version.
        target_formula_profile (Mapped[str]): 再計算で使うformula profile.
        candidate_count (Mapped[int]): batchに登録したcandidate数.
        completed_count (Mapped[int]): 成功完了したwork item数.
        unavailable_count (Mapped[int]): unavailable完了したwork item数.
        created_at (Mapped[datetime]): batchを作成したUTC timestamp.
        updated_at (Mapped[datetime]): batchを最後に更新したUTC timestamp.
    """

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
    """recalculation batch内の1 scoreとworker claimを保存する.

    Attributes:
        __tablename__ (str): 保存先のperformance_recalculation_work_items table名.
        __table_args__ (tuple[CheckConstraint | Index, ...]):
            claim整合性とqueue lookupを支えるconstraint/index.
        id (Mapped[int]): 自動採番するwork itemのprimary key.
        batch_id (Mapped[int]): 所属recalculation batchのforeign key.
        score_id (Mapped[int]): 再計算対象scoreのforeign key.
        reason (Mapped[str]): work itemを作成したrecalculation理由.
        state (Mapped[str]): pending/claimed/completedなどのwork item状態.
        calculation_id (Mapped[int | None]): 実行結果calculationのforeign key. 未完了ならNULL.
        claim_owner (Mapped[str | None]): itemを処理するworkerの識別子. claimed以外はNULL.
        claim_expires_at (Mapped[datetime | None]):
            worker lease失効UTC timestamp. claimed以外はNULL.
        attempt_count (Mapped[int]): workerがclaimした試行回数.
        last_error (Mapped[str | None]): 最後の失敗理由. 失敗前はNULL.
        created_at (Mapped[datetime]): work itemを作成したUTC timestamp.
        updated_at (Mapped[datetime]): work itemを最後に更新したUTC timestamp.

    Notes:
        claimed状態だけがclaim_ownerとclaim_expires_atを持つ.
        pendingとterminal状態では両方をNULLにする.
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
