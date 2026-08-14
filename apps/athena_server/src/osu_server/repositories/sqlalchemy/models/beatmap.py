"""beatmap metadataと取得状態を保存するSQLAlchemy ORM modelを定義する.

official metadataとlocal overrideを分離する.
beatmap file attachmentと取得retry stateも同じbounded contextで保持する.
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
    UniqueConstraint,
    column,
    func,
    or_,
)
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models.enum_types import (
    BEATMAP_DIRECT_COVERAGE_KIND_ENUM,
    BEATMAP_DIRECT_EXTERNAL_INDEX_BACKEND_ENUM,
    BEATMAP_DIRECT_EXTERNAL_INDEX_STATUS_ENUM,
    BEATMAP_DIRECT_STATUS_SCOPE_ENUM,
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
_SEARCH_DOCUMENT_VERSION_COLUMN = column("search_document_version", Integer)
_COVERAGE_FROM_BEATMAPSET_ID_COLUMN = column("from_beatmapset_id", Integer)
_COVERAGE_TO_BEATMAPSET_ID_COLUMN = column("to_beatmapset_id", Integer)
_COVERAGE_COMPLETED_AT_COLUMN = column("completed_at", DateTime(timezone=True))
_COVERAGE_FAILED_AT_COLUMN = column("failed_at", DateTime(timezone=True))
_INDEX_STATE_DOCUMENT_VERSION_COLUMN = column("document_version", Integer)
_INDEX_STATE_FAILURE_REASON_COLUMN = column("failure_reason", Text)
_INDEX_STATE_STATUS_COLUMN = column("status", String(length=16))


class BeatmapSetModel(Base):
    """beatmap setに共有されるofficial metadata snapshotを表す.

    Attributes:
        __tablename__ (str): 保存先のbeatmapsets table名.
        __table_args__ (tuple[Index | CheckConstraint, ...]): 検索version制約とlookup index.
        id (Mapped[int]): osu!が割り当てるbeatmap set識別子.
        artist (Mapped[str]): 主表示用artist名.
        title (Mapped[str]): 主表示用title.
        creator (Mapped[str]): beatmap setを作成したmapper名.
        artist_unicode (Mapped[str | None]): Unicode artist名. 未提供ならNULL.
        title_unicode (Mapped[str | None]): Unicode title. 未提供ならNULL.
        source_text (Mapped[str]): 曲の出典検索文字列. 未提供なら空文字列.
        tags (Mapped[str]): tag検索文字列. 未提供なら空文字列.
        direct_search_text (Mapped[str]): ParadeDB/tsvector向けのmaterialized検索入力.
        official_status (Mapped[str]): upstreamが報告したrank status.
        official_status_source (Mapped[str]): official statusを得たmetadata source.
        official_status_verified (Mapped[bool]): statusが信頼できるsourceで確認済みか.
        last_fetched_at (Mapped[datetime | None]): metadataを最後に取得したUTC timestamp.
        next_refresh_at (Mapped[datetime | None]): 次のmetadata refresh予定UTC timestamp.
        official_submitted_at (Mapped[datetime | None]): upstream投稿日時のUTC timestamp.
        official_ranked_at (Mapped[datetime | None]): upstream ranked日時のUTC timestamp.
        official_last_updated_at (Mapped[datetime | None]): upstream metadata更新のUTC timestamp.
        search_document_version (Mapped[int]): 検索入力の更新version.
        search_document_updated_at (Mapped[datetime]): 検索入力を最後に更新したUTC timestamp.
        created_at (Mapped[datetime]): recordを作成したUTC timestamp.
        updated_at (Mapped[datetime]): recordを最後に更新したUTC timestamp.
    """

    __tablename__: str = "beatmapsets"
    __table_args__: tuple[Index | CheckConstraint, ...] = (
        CheckConstraint(
            _SEARCH_DOCUMENT_VERSION_COLUMN > 0,
            name="ck_beatmapsets_search_document_version_positive",
        ),
        Index(
            "idx_beatmapsets_direct_status_update",
            "official_status",
            "search_document_updated_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    artist: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    creator: Mapped[str] = mapped_column(String(255), nullable=False)
    artist_unicode: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title_unicode: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_text: Mapped[str] = mapped_column("source", Text, nullable=False, server_default="")
    tags: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    direct_search_text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
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
    official_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    official_ranked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    official_last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    search_document_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    search_document_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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
    """1 difficultyのofficial metadataとserver-local stateを表す.

    Attributes:
        __tablename__ (str): 保存先のbeatmaps table名.
        __table_args__ (tuple[UniqueConstraint | Index | CheckConstraint, ...]):
            checksum一意性とcount制約および検索index.
        id (Mapped[int]): osu!が割り当てるbeatmap識別子.
        beatmapset_id (Mapped[int]): 所属beatmap setのforeign key.
        checksum_md5 (Mapped[str | None]): .osu fileのMD5 checksum. 未確認ならNULL.
        mode (Mapped[str]): beatmap ruleset種別.
        version (Mapped[str]): difficulty version名.
        total_length (Mapped[int | None]): breakを含む総play length秒数. 未提供ならNULL.
        hit_length (Mapped[int | None]): hit object区間のplay length秒数. 未提供ならNULL.
        max_combo (Mapped[int | None]): map上の最大combo. 未提供ならNULL.
        bpm (Mapped[Decimal | None]): beatmap BPM. 未提供ならNULL.
        cs (Mapped[Decimal | None]): circle size. 未提供ならNULL.
        od (Mapped[Decimal | None]): overall difficulty. 未提供ならNULL.
        ar (Mapped[Decimal | None]): approach rate. 未提供ならNULL.
        hp (Mapped[Decimal | None]): HP drain rate. 未提供ならNULL.
        difficulty_rating (Mapped[Decimal | None]): upstream difficulty rating. 未提供ならNULL.
        official_status (Mapped[str]): upstreamが報告したrank status.
        official_status_source (Mapped[str]): official statusを得たmetadata source.
        official_status_verified (Mapped[bool]): statusが信頼できるsourceで確認済みか.
        local_status_override (Mapped[str | None]): serverが設定したlocal status. 未設定ならNULL.
        local_status_override_changed_at (Mapped[datetime | None]):
            local overrideを変更したUTC timestamp.
        play_count (Mapped[int]): serverで受理したplay数. 負値は保存できない.
        pass_count (Mapped[int]): passed play数. play_countを超えられない.
        official_last_updated_at (Mapped[datetime | None]): upstream metadata更新のUTC timestamp.
        last_fetched_at (Mapped[datetime | None]): metadataを最後に取得したUTC timestamp.
        next_refresh_at (Mapped[datetime | None]): 次のmetadata refresh予定UTC timestamp.
        created_at (Mapped[datetime]): recordを作成したUTC timestamp.
        updated_at (Mapped[datetime]): recordを最後に更新したUTC timestamp.
    """

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
    """beatmapの取得済み.osu fileとblobを結び付ける.

    Attributes:
        __tablename__ (str): 保存先のbeatmap_file_attachments table名.
        __table_args__ (tuple[UniqueConstraint | Index, ...]): beatmap/checksum一意性と検索index.
        id (Mapped[int]): 自動採番するattachmentのprimary key.
        beatmap_id (Mapped[int]): attachment先beatmapのforeign key.
        blob_id (Mapped[int]): .osu file contentを持つblobのforeign key.
        checksum_md5 (Mapped[str]): sourceが示した32文字MD5 checksum.
        verified_md5 (Mapped[str | None]): Athenaが検証したMD5 checksum. 未検証ならNULL.
        source (Mapped[str]): fileを取得したsource種別.
        original_filename (Mapped[str | None]): source上のfile名. 未提供ならNULL.
        fetched_at (Mapped[datetime]): fileを取得したUTC timestamp.
        verified_at (Mapped[datetime | None]): checksumを検証したUTC timestamp. 未検証ならNULL.
        created_at (Mapped[datetime]): attachmentを作成したUTC timestamp.
    """

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
    """beatmap metadataまたはfile取得のretry stateを表す.

    Attributes:
        __tablename__ (str): 保存先のbeatmap_fetch_states table名.
        __table_args__ (tuple[UniqueConstraint | Index, ...]): target一意性とstatus lookup index.
        id (Mapped[int]): 自動採番するfetch stateのprimary key.
        target_type (Mapped[str]): metadata/fileなどの取得対象種別.
        target_key (Mapped[str]): target_type内で一意な取得対象key.
        status (Mapped[str]): pending/succeeded/failedなどの取得状態.
        attempt_count (Mapped[int]): retryを含む取得試行回数.
        last_error (Mapped[str | None]): 最後の失敗理由. 成功時または未試行ならNULL.
        pending_since (Mapped[datetime | None]): pending状態へ遷移したUTC timestamp.
        last_attempted_at (Mapped[datetime | None]): 最後に取得を試行したUTC timestamp.
        updated_at (Mapped[datetime]): stateを最後に更新したUTC timestamp.
    """

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


class BeatmapDirectCoverageModel(Base):
    """osu!direct catalog同期のcoverageと失敗状態を表す.

    Attributes:
        __tablename__ (str): 保存先のbeatmap_direct_coverage table名.
        __table_args__ (tuple[UniqueConstraint | Index | CheckConstraint, ...]):
            coverage scope一意性, 範囲制約, 完了/失敗状態制約, lookup index.
        id (Mapped[int]): 自動採番するcoverage recordのprimary key.
        coverage_kind (Mapped[str]): feed windowまたはid range crawlを区別する種別.
        source (Mapped[str]): upstream source識別子.
        status_scope (Mapped[str]): 同期対象status scope. 全体対象はallを保存する.
        sort_key (Mapped[str]): feed sortまたはid crawl種別.
        window_key (Mapped[str]): cursor/page/window識別子. id chunkでは空文字列を保存する.
        from_beatmapset_id (Mapped[int]): 観測またはcrawlした範囲開始id. 未特定なら0.
        to_beatmapset_id (Mapped[int]): 観測またはcrawlした範囲終了id. 未特定なら0.
        cursor (Mapped[str | None]): upstream cursor. 未提供ならNULL.
        completed_at (Mapped[datetime | None]): coverage完了時刻. 失敗recordではNULL.
        failed_at (Mapped[datetime | None]): 同期失敗時刻. 完了recordではNULL.
        failure_reason (Mapped[str | None]): sanitized failure reason. 成功時または未記録ならNULL.
    """

    __tablename__: str = "beatmap_direct_coverage"
    __table_args__: tuple[UniqueConstraint | Index | CheckConstraint, ...] = (
        UniqueConstraint(
            "coverage_kind",
            "source",
            "status_scope",
            "sort_key",
            "window_key",
            "from_beatmapset_id",
            "to_beatmapset_id",
            name="uq_beatmap_direct_coverage_scope",
        ),
        CheckConstraint(
            _COVERAGE_FROM_BEATMAPSET_ID_COLUMN >= 0,
            name="ck_beatmap_direct_coverage_range_non_negative",
        ),
        CheckConstraint(
            _COVERAGE_TO_BEATMAPSET_ID_COLUMN >= _COVERAGE_FROM_BEATMAPSET_ID_COLUMN,
            name="ck_beatmap_direct_coverage_range_ordered",
        ),
        CheckConstraint(
            or_(_COVERAGE_COMPLETED_AT_COLUMN.is_(None), _COVERAGE_FAILED_AT_COLUMN.is_(None)),
            name="ck_beatmap_direct_coverage_not_completed_and_failed",
        ),
        CheckConstraint(
            or_(column("failure_reason", Text).is_(None), _COVERAGE_FAILED_AT_COLUMN.is_not(None)),
            name="ck_beatmap_direct_coverage_failure_reason_requires_failed_at",
        ),
        Index(
            "idx_beatmap_direct_coverage_scope_lookup",
            "coverage_kind",
            "source",
            "status_scope",
            "sort_key",
            "window_key",
        ),
        Index("idx_beatmap_direct_coverage_failure_lookup", "failed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    coverage_kind: Mapped[str] = mapped_column(BEATMAP_DIRECT_COVERAGE_KIND_ENUM, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status_scope: Mapped[str] = mapped_column(BEATMAP_DIRECT_STATUS_SCOPE_ENUM, nullable=False)
    sort_key: Mapped[str] = mapped_column(Text, nullable=False)
    window_key: Mapped[str] = mapped_column(Text, nullable=False)
    from_beatmapset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    to_beatmapset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class BeatmapDirectExternalIndexStateModel(Base):
    """osu!direct optional external indexのdocument同期状態を表す.

    Attributes:
        __tablename__ (str): 保存先のbeatmap_direct_external_index_state table名.
        __table_args__ (tuple[UniqueConstraint | Index | CheckConstraint, ...]):
            document version制約, failure reason制約, retry lookup index.
        backend (Mapped[str]): external index backend識別子.
        beatmapset_id (Mapped[int]): external document対象のbeatmap set識別子.
        document_version (Mapped[int]): 同期を試行したprojection version.
        status (Mapped[str]): pending, succeeded, failedの同期状態.
        last_attempted_at (Mapped[datetime | None]): 最後に同期を試行した時刻.
        last_succeeded_at (Mapped[datetime | None]): 最後に同期成功した時刻.
        failure_reason (Mapped[str | None]): sanitized failure reason. 失敗時以外はNULL.
    """

    __tablename__: str = "beatmap_direct_external_index_state"
    __table_args__: tuple[UniqueConstraint | Index | CheckConstraint, ...] = (
        CheckConstraint(
            _INDEX_STATE_DOCUMENT_VERSION_COLUMN > 0,
            name="ck_beatmap_direct_index_state_version_positive",
        ),
        CheckConstraint(
            or_(
                _INDEX_STATE_FAILURE_REASON_COLUMN.is_(None),
                _INDEX_STATE_STATUS_COLUMN == "failed",
            ),
            name="ck_beatmap_direct_index_state_failure_reason",
        ),
        Index(
            "idx_beatmap_direct_external_index_state_status_lookup",
            "backend",
            "status",
            "last_attempted_at",
        ),
    )

    backend: Mapped[str] = mapped_column(
        BEATMAP_DIRECT_EXTERNAL_INDEX_BACKEND_ENUM,
        primary_key=True,
    )
    beatmapset_id: Mapped[int] = mapped_column(
        ForeignKey(
            "beatmapsets.id",
            name="fk_beatmap_direct_external_index_state_beatmapset_id",
        ),
        primary_key=True,
        autoincrement=False,
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        BEATMAP_DIRECT_EXTERNAL_INDEX_STATUS_ENUM,
        nullable=False,
    )
    last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_succeeded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
