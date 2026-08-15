"""osu!direct search inputとcoverage stateを作成するmigration.

Revision ID: 20260809_0100
Revises: 20260713_0700
Create Date: 2026-08-09 01:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260809_0100"
down_revision: str | None = "20260713_0700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEATMAPSET_TABLE = "beatmapsets"
_COVERAGE_TABLE = "beatmap_direct_coverage"
_EXTERNAL_INDEX_STATE_TABLE = "beatmap_direct_external_index_state"
_SEARCH_DOCUMENT_BM25_INDEX = "idx_beatmapsets_direct_search_bm25"
_SEARCH_DOCUMENT_ACTIVE_STATUS_INDEX = "idx_beatmapsets_direct_status_update"
_SEARCH_DOCUMENT_VERSION_CONSTRAINT = "ck_beatmapsets_search_document_version_positive"
_COVERAGE_SCOPE_INDEX = "idx_beatmap_direct_coverage_scope_lookup"
_COVERAGE_FAILURE_INDEX = "idx_beatmap_direct_coverage_failure_lookup"
_EXTERNAL_INDEX_STATE_STATUS_INDEX = "idx_beatmap_direct_external_index_state_status_lookup"
_SEARCH_DOCUMENT_PARADEDB_FIELDS = (
    "id",
    "direct_search_text",
)
_PG_AVAILABLE_EXTENSION = sa.table("pg_available_extensions", sa.column("name", sa.String()))
_PG_EXTENSION = sa.table("pg_extension", sa.column("extname", sa.String()))
_PARADEDB_EXTENSION = "pg_search"
_VECTOR_EXTENSION = "vector"
_SEARCH_DOCUMENT_VERSION_COLUMN = sa.column("search_document_version", sa.Integer())
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
    """osu!direct search input, coverage, external index stateを作成する.

    Returns:
        None: beatmapsets検索入力, coverage, index state table, optional検索indexを
            作成したことを示す.

    Raises:
        SQLAlchemyError: pg_search利用可能環境でextension有効化またはBM25 index作成に失敗した場合.
    """
    _prepare_optional_paradedb_index_dependencies()

    op.add_column(
        _BEATMAPSET_TABLE,
        sa.Column("source", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        _BEATMAPSET_TABLE,
        sa.Column("tags", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        _BEATMAPSET_TABLE,
        sa.Column("direct_search_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        _BEATMAPSET_TABLE,
        sa.Column("search_document_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        _BEATMAPSET_TABLE,
        sa.Column(
            "search_document_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_check_constraint(
        _SEARCH_DOCUMENT_VERSION_CONSTRAINT,
        _BEATMAPSET_TABLE,
        _SEARCH_DOCUMENT_VERSION_COLUMN > 0,
    )
    with op.get_context().autocommit_block():
        op.create_index(
            _SEARCH_DOCUMENT_ACTIVE_STATUS_INDEX,
            _BEATMAPSET_TABLE,
            ["official_status", "search_document_updated_at", "id"],
            postgresql_concurrently=True,
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
    """osu!direct search input, coverage, external index stateを削除する.

    Returns:
        None: 追加したindex, column, tableを依存順に削除したことを示す.
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
        table_name=_BEATMAPSET_TABLE,
        if_exists=True,
    )
    op.drop_constraint(
        _SEARCH_DOCUMENT_VERSION_CONSTRAINT,
        _BEATMAPSET_TABLE,
        type_="check",
    )
    op.drop_column(_BEATMAPSET_TABLE, "search_document_updated_at")
    op.drop_column(_BEATMAPSET_TABLE, "search_document_version")
    op.drop_column(_BEATMAPSET_TABLE, "direct_search_text")
    op.drop_column(_BEATMAPSET_TABLE, "tags")
    op.drop_column(_BEATMAPSET_TABLE, "source")


def _create_search_document_bm25_index() -> None:
    """ParadeDB indexをbeatmapsetsのmaterialized検索入力へ作成する.

    Returns:
        None: pg_search利用可能時だけmaterialized検索入力を含むParadeDB indexを作成したことを示す.
    """
    if not _paradedb_extensions_available():
        return

    fields = ", ".join(_SEARCH_DOCUMENT_PARADEDB_FIELDS)
    create_index_sql = f"CREATE INDEX CONCURRENTLY {_SEARCH_DOCUMENT_BM25_INDEX} "
    create_index_sql += f"ON {_BEATMAPSET_TABLE} USING paradedb ({fields}) WITH (key_field='id')"
    with op.get_context().autocommit_block():
        op.execute(sa.text(create_index_sql))


def _paradedb_extensions_available() -> bool:
    """ParadeDB依存extensionをこのdatabaseで作成できるか返す.

    Returns:
        bool: vectorとpg_searchがPostgreSQL installationへ存在する場合はTrue.
    """
    return _postgres_extension_available(_VECTOR_EXTENSION) and _postgres_extension_available(
        _PARADEDB_EXTENSION
    )


def _postgres_extension_available(extension_name: str) -> bool:
    """PostgreSQL installationで指定extensionが利用可能か返す.

    Args:
        extension_name (str): `pg_available_extensions`で確認するextension名.

    Returns:
        bool: 指定extensionが現在databaseで作成可能な場合はTrue.
    """
    statement = (
        sa.select(sa.literal(True))
        .select_from(_PG_AVAILABLE_EXTENSION)
        .where(_PG_AVAILABLE_EXTENSION.c.name == extension_name)
        .limit(1)
    )
    return bool(op.get_bind().execute(statement).scalar_one_or_none())


def _prepare_optional_paradedb_index_dependencies() -> None:
    """Optional ParadeDB indexに必要なextensionをschema DDL前に有効化する.

    Returns:
        None: extension未導入環境では何もせず,利用可能環境では有効化を完了する.

    Raises:
        SQLAlchemyError: extension作成権限不足またはDDL失敗が発生した場合.

    Notes:
        extension作成失敗時にrevisionをclean retryできるよう, column追加やindex作成より先に行う.
    """
    if not _paradedb_extensions_available():
        return
    with op.get_context().autocommit_block():
        _ensure_paradedb_extensions_created()


def _postgres_extension_created(extension_name: str) -> bool:
    """現在databaseで指定extensionが作成済みか返す.

    Args:
        extension_name (str): `pg_extension`で確認するextension名.

    Returns:
        bool: 指定extensionが現在databaseで有効化済みの場合はTrue.
    """
    statement = (
        sa.select(sa.literal(True))
        .select_from(_PG_EXTENSION)
        .where(_PG_EXTENSION.c.extname == extension_name)
        .limit(1)
    )
    return bool(op.get_bind().execute(statement).scalar_one_or_none())


def _ensure_paradedb_extensions_created() -> None:
    """ParadeDB依存extensionを現在databaseで有効化する.

    Returns:
        None: vectorとpg_searchが現在databaseで有効化されたことを示す.

    Raises:
        SQLAlchemyError: extension作成権限不足またはDDL失敗が発生した場合.
    """
    if not _postgres_extension_created(_VECTOR_EXTENSION):
        _create_extension_if_missing(_VECTOR_EXTENSION)
    if not _postgres_extension_created(_PARADEDB_EXTENSION):
        _create_extension_if_missing(_PARADEDB_EXTENSION)


def _create_extension_if_missing(extension_name: str) -> None:
    """指定extensionをdatabaseへ作成済みにする.

    Args:
        extension_name (str): `CREATE EXTENSION IF NOT EXISTS`へ渡すextension名.

    Returns:
        None: extension作成DDLを発行して完了する.
    """
    op.execute(sa.text(f"CREATE EXTENSION IF NOT EXISTS {extension_name}"))


def _drop_search_document_bm25_index() -> None:
    """ParadeDB indexを存在時だけ削除する.

    Returns:
        None: search document ParadeDB indexを削除または不在のまま確認したことを示す.
    """
    with op.get_context().autocommit_block():
        op.drop_index(
            _SEARCH_DOCUMENT_BM25_INDEX,
            table_name=_BEATMAPSET_TABLE,
            if_exists=True,
            postgresql_concurrently=True,
        )
