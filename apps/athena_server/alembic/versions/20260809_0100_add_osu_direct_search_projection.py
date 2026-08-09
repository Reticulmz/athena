"""osu!direct search projectionとcoverage stateを作成するmigration.

Revision ID: 20260809_0100
Revises: 20260713_0700
Create Date: 2026-08-09 01:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260809_0100"
down_revision: str | None = "20260713_0700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEATMAP_MODE_VALUES = ("osu", "taiko", "fruits", "mania", "unknown")
_SEARCH_DOCUMENT_TABLE = "beatmapset_search_documents"
_COVERAGE_TABLE = "beatmap_direct_coverage"
_EXTERNAL_INDEX_STATE_TABLE = "beatmap_direct_external_index_state"
_SEARCH_DOCUMENT_BM25_INDEX = "idx_beatmapset_search_documents_bm25"
_SEARCH_DOCUMENT_ACTIVE_STATUS_INDEX = "idx_beatmapset_search_documents_active_status_update"
_COVERAGE_SCOPE_INDEX = "idx_beatmap_direct_coverage_scope_lookup"
_COVERAGE_FAILURE_INDEX = "idx_beatmap_direct_coverage_failure_lookup"
_EXTERNAL_INDEX_STATE_STATUS_INDEX = "idx_beatmap_direct_external_index_state_status_lookup"
_SEARCH_DOCUMENT_MODES_COLUMN = sa.column(
    "modes",
    postgresql.ARRAY(sa.String(length=16)),
)
_SEARCH_DOCUMENT_VERSION_COLUMN = sa.column("document_version", sa.Integer())
_COVERAGE_FROM_BEATMAPSET_ID_COLUMN = sa.column("from_beatmapset_id", sa.Integer())
_COVERAGE_TO_BEATMAPSET_ID_COLUMN = sa.column("to_beatmapset_id", sa.Integer())
_COVERAGE_COMPLETED_AT_COLUMN = sa.column("completed_at", sa.DateTime(timezone=True))
_COVERAGE_FAILED_AT_COLUMN = sa.column("failed_at", sa.DateTime(timezone=True))
_COVERAGE_FAILURE_REASON_COLUMN = sa.column("failure_reason", sa.Text())
_INDEX_STATE_DOCUMENT_VERSION_COLUMN = sa.column("document_version", sa.Integer())
_INDEX_STATE_FAILURE_REASON_COLUMN = sa.column("failure_reason", sa.Text())
_INDEX_STATE_STATUS_COLUMN = sa.column("status", sa.String(length=16))


def _checked_string_enum(
    *values: str,
    name: str,
    length: int,
) -> sa.Enum:
    """CHECK constraintを持つnon-native string Enumを構築する.

    Args:
        *values (str): migration時点で許可する閉集合の文字列値.
        name (str): EnumとCHECK constraintに使用する固定名.
        length (int): 保存する文字列の最大長.

    Returns:
        sa.Enum: native enumを使わずnamed CHECK constraintを生成するSQLAlchemy型.

    Notes:
        accepted valueはrevision内にsnapshotし, mutableなdomain Enumをimportしない.
    """
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=length,
    )


BEATMAP_RANK_STATUS_ENUM = _checked_string_enum(
    "ranked",
    "approved",
    "loved",
    "qualified",
    "pending",
    "wip",
    "graveyard",
    "not_submitted",
    "unknown",
    name="ck_beatmap_rank_status_known",
    length=32,
)
BEATMAP_DIRECT_STATUS_SCOPE_ENUM = _checked_string_enum(
    "all",
    "ranked",
    "approved",
    "loved",
    "qualified",
    "pending",
    "wip",
    "graveyard",
    "not_submitted",
    "unknown",
    name="ck_beatmap_direct_coverage_status_scope_known",
    length=32,
)
BEATMAP_DIRECT_COVERAGE_KIND_ENUM = _checked_string_enum(
    "feed_window",
    "id_range",
    name="ck_beatmap_direct_coverage_kind_known",
    length=16,
)
BEATMAP_DIRECT_EXTERNAL_INDEX_BACKEND_ENUM = _checked_string_enum(
    "meilisearch",
    name="ck_beatmap_direct_external_index_state_backend_known",
    length=32,
)
BEATMAP_DIRECT_EXTERNAL_INDEX_STATUS_ENUM = _checked_string_enum(
    "pending",
    "succeeded",
    "failed",
    name="ck_beatmap_direct_external_index_state_status_known",
    length=16,
)


def upgrade() -> None:
    """osu!direct search projection, coverage, external index stateを作成する.

    Returns:
        None: projection, coverage, index state tableと検索indexを作成したことを示す.

    Raises:
        SQLAlchemyError: pg_search extension有効化またはBM25 index作成に失敗した場合.
    """
    _ = op.create_table(
        _SEARCH_DOCUMENT_TABLE,
        sa.Column("beatmapset_id", sa.Integer(), nullable=False),
        sa.Column("artist", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("creator", sa.String(length=255), nullable=False),
        sa.Column("artist_unicode", sa.String(length=255), nullable=True),
        sa.Column("title_unicode", sa.String(length=255), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("tags", sa.Text(), nullable=False),
        sa.Column("difficulty_names", sa.Text(), nullable=False),
        sa.Column("modes", postgresql.ARRAY(sa.String(length=16)), nullable=False),
        sa.Column("status", BEATMAP_RANK_STATUS_ENUM, nullable=False),
        sa.Column("last_update_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("beatmapset_id", name="pk_beatmapset_search_documents"),
        sa.ForeignKeyConstraint(
            ["beatmapset_id"],
            ["beatmapsets.id"],
            name="fk_beatmapset_search_documents_beatmapset_id",
        ),
        sa.CheckConstraint(
            _SEARCH_DOCUMENT_VERSION_COLUMN > 0,
            name="ck_beatmapset_search_documents_document_version_positive",
        ),
        sa.CheckConstraint(
            sa.func.cardinality(_SEARCH_DOCUMENT_MODES_COLUMN) > 0,
            name="ck_beatmapset_search_documents_modes_not_empty",
        ),
        sa.CheckConstraint(
            _SEARCH_DOCUMENT_MODES_COLUMN.op("<@")(
                postgresql.array(_BEATMAP_MODE_VALUES, type_=sa.String(length=16))
            ),
            name="ck_beatmapset_search_documents_modes_known",
        ),
    )
    op.create_index(
        _SEARCH_DOCUMENT_ACTIVE_STATUS_INDEX,
        _SEARCH_DOCUMENT_TABLE,
        ["is_active", "status", "last_update_at", "beatmapset_id"],
    )
    _create_search_document_bm25_index()

    _ = op.create_table(
        _COVERAGE_TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("coverage_kind", BEATMAP_DIRECT_COVERAGE_KIND_ENUM, nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status_scope", BEATMAP_DIRECT_STATUS_SCOPE_ENUM, nullable=False),
        sa.Column("sort_key", sa.Text(), nullable=False),
        sa.Column("window_key", sa.Text(), nullable=False),
        sa.Column("from_beatmapset_id", sa.Integer(), nullable=False),
        sa.Column("to_beatmapset_id", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "coverage_kind",
            "source",
            "status_scope",
            "sort_key",
            "window_key",
            "from_beatmapset_id",
            "to_beatmapset_id",
            name="uq_beatmap_direct_coverage_scope",
        ),
        sa.CheckConstraint(
            _COVERAGE_FROM_BEATMAPSET_ID_COLUMN >= 0,
            name="ck_beatmap_direct_coverage_range_non_negative",
        ),
        sa.CheckConstraint(
            _COVERAGE_TO_BEATMAPSET_ID_COLUMN >= _COVERAGE_FROM_BEATMAPSET_ID_COLUMN,
            name="ck_beatmap_direct_coverage_range_ordered",
        ),
        sa.CheckConstraint(
            sa.or_(_COVERAGE_COMPLETED_AT_COLUMN.is_(None), _COVERAGE_FAILED_AT_COLUMN.is_(None)),
            name="ck_beatmap_direct_coverage_not_completed_and_failed",
        ),
        sa.CheckConstraint(
            sa.or_(
                _COVERAGE_FAILURE_REASON_COLUMN.is_(None),
                _COVERAGE_FAILED_AT_COLUMN.is_not(None),
            ),
            name="ck_beatmap_direct_coverage_failure_reason_requires_failed_at",
        ),
    )
    op.create_index(
        _COVERAGE_SCOPE_INDEX,
        _COVERAGE_TABLE,
        ["coverage_kind", "source", "status_scope", "sort_key", "window_key"],
    )
    op.create_index(_COVERAGE_FAILURE_INDEX, _COVERAGE_TABLE, ["failed_at"])

    _ = op.create_table(
        _EXTERNAL_INDEX_STATE_TABLE,
        sa.Column("backend", BEATMAP_DIRECT_EXTERNAL_INDEX_BACKEND_ENUM, nullable=False),
        sa.Column("beatmapset_id", sa.Integer(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("status", BEATMAP_DIRECT_EXTERNAL_INDEX_STATUS_ENUM, nullable=False),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint(
            "backend",
            "beatmapset_id",
            name="pk_beatmap_direct_external_index_state",
        ),
        sa.ForeignKeyConstraint(
            ["beatmapset_id"],
            ["beatmapsets.id"],
            name="fk_beatmap_direct_external_index_state_beatmapset_id",
        ),
        sa.CheckConstraint(
            _INDEX_STATE_DOCUMENT_VERSION_COLUMN > 0,
            name="ck_beatmap_direct_index_state_version_positive",
        ),
        sa.CheckConstraint(
            sa.or_(
                _INDEX_STATE_FAILURE_REASON_COLUMN.is_(None),
                _INDEX_STATE_STATUS_COLUMN == "failed",
            ),
            name="ck_beatmap_direct_index_state_failure_reason",
        ),
    )
    op.create_index(
        _EXTERNAL_INDEX_STATE_STATUS_INDEX,
        _EXTERNAL_INDEX_STATE_TABLE,
        ["backend", "status", "last_attempted_at"],
    )


def downgrade() -> None:
    """osu!direct search projection, coverage, external index stateを削除する.

    Returns:
        None: 追加したindexとtableを依存順に削除したことを示す.
    """
    op.drop_index(
        _EXTERNAL_INDEX_STATE_STATUS_INDEX,
        table_name=_EXTERNAL_INDEX_STATE_TABLE,
        if_exists=True,
    )
    op.drop_table(_EXTERNAL_INDEX_STATE_TABLE)
    op.drop_index(_COVERAGE_FAILURE_INDEX, table_name=_COVERAGE_TABLE, if_exists=True)
    op.drop_index(_COVERAGE_SCOPE_INDEX, table_name=_COVERAGE_TABLE, if_exists=True)
    op.drop_table(_COVERAGE_TABLE)
    _drop_search_document_bm25_index()
    op.drop_index(
        _SEARCH_DOCUMENT_ACTIVE_STATUS_INDEX,
        table_name=_SEARCH_DOCUMENT_TABLE,
        if_exists=True,
    )
    op.drop_table(_SEARCH_DOCUMENT_TABLE)


def _create_search_document_bm25_index() -> None:
    """ParadeDB BM25 indexをsearch document tableへ作成する.

    Returns:
        None: search/filter/sort columnを含むBM25 indexを作成したことを示す.

    Notes:
        SQLAlchemy/Alembicは`USING bm25`と`WITH (key_field = ...)`を構造化APIで
        表現できないため, このDDLだけtextual SQLで実行する.
    """
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_search"))
    op.execute(
        sa.text(
            """
            CREATE INDEX idx_beatmapset_search_documents_bm25
            ON beatmapset_search_documents
            USING bm25 (
                beatmapset_id,
                artist,
                title,
                creator,
                source,
                tags,
                difficulty_names,
                artist_unicode,
                title_unicode,
                status,
                modes,
                last_update_at
            )
            WITH (key_field = 'beatmapset_id')
            """
        )
    )


def _drop_search_document_bm25_index() -> None:
    """ParadeDB BM25 indexを存在時だけ削除する.

    Returns:
        None: search document BM25 indexを削除または不在のまま確認したことを示す.

    Notes:
        SQLAlchemy/AlembicはBM25 indexのdialect optionを表現できないため,
        作成側と同じくtextual SQLで削除する.
    """
    op.execute(sa.text("DROP INDEX IF EXISTS idx_beatmapset_search_documents_bm25"))
