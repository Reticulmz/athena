"""osu!direct search input migrationのschema contractを検証する."""

from typing import cast

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models import (
    BeatmapDirectCoverageModel,
    BeatmapDirectExternalIndexStateModel,
    BeatmapSetModel,
)
from tests.support.paths import ALEMBIC_VERSIONS_ROOT

MIGRATION_PATH = ALEMBIC_VERSIONS_ROOT / "20260809_0100_add_osu_direct_search_projection.py"


def _column(table: Table, name: str) -> Column[object]:
    """Tableから指定名のcolumnをtyped Columnとして取得する.

    Args:
        table (Table): columnを所有するSQLAlchemy table metadata.
        name (str): 存在することを前提に取得するcolumn名.

    Returns:
        Column[object]: 指定名に対応するtyped column.

    Raises:
        KeyError: tableにnameのcolumnが存在しない場合.
    """
    return cast("Column[object]", table.c[name])


def _checked_enum_values(column: Column[object]) -> tuple[str, ...]:
    """CHECK制約付きSQLAlchemy Enumから保存可能値を取得する.

    Args:
        column (Column[object]): SQLAlchemy Enum型で宣言されたcolumn.

    Returns:
        tuple[str, ...]: columnが保存できる閉集合の文字列値.
    """
    enum_type = cast("sa.Enum", column.type)
    assert cast("bool", enum_type.native_enum) is False
    assert cast("bool", enum_type.create_constraint) is True
    assert cast("bool", enum_type.validate_strings) is True
    return tuple(str(value) for value in enum_type.enums)


def _string_length(column: Column[object]) -> int | None:
    """String columnの宣言済み最大長を取得する.

    Args:
        column (Column[object]): String型であることを前提にしたcolumn.

    Returns:
        int | None: String型に設定された最大長. 長さ未指定時はNone.
    """
    return cast("String", column.type).length


def _check_constraint_names(table: Table) -> set[str]:
    """Tableの名前付きCHECK constraint名を抽出する.

    Args:
        table (Table): CHECK constraintを検証するSQLAlchemy table metadata.

    Returns:
        set[str]: tableに定義された名前付きCHECK constraint名.
    """
    return {
        cast("str", constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }


def _unique_constraints(table: Table) -> dict[str, tuple[str, ...]]:
    """Tableの名前付きunique constraintをcolumn順序へ変換する.

    Args:
        table (Table): unique constraintを検証するSQLAlchemy table metadata.

    Returns:
        dict[str, tuple[str, ...]]: constraint名ごとの対象column順序.
    """
    constraints: dict[str, tuple[str, ...]] = {}
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint) and constraint.name is not None:
            constraint_name = cast("str", constraint.name)
            constraints[constraint_name] = tuple(column.name for column in constraint.columns)
    return constraints


def _foreign_key_constraints(table: Table) -> dict[str, tuple[str, str]]:
    """Tableの名前付きforeign key constraintをcolumn対応表へ変換する.

    Args:
        table (Table): foreign key constraintを検証するSQLAlchemy table metadata.

    Returns:
        dict[str, tuple[str, str]]: constraint名ごとのsource columnとtarget column.
    """
    constraints: dict[str, tuple[str, str]] = {}
    for constraint in table.constraints:
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name is not None:
            constraint_name = cast("str", constraint.name)
            source_column = next(iter(constraint.columns)).name
            target_column = cast("str", next(iter(constraint.elements)).target_fullname)
            constraints[constraint_name] = (source_column, target_column)
    return constraints


def _indexes(table: Table) -> dict[str, tuple[str, ...]]:
    """Tableの名前付きindexを対象column順序へ変換する.

    Args:
        table (Table): indexを検証するSQLAlchemy table metadata.

    Returns:
        dict[str, tuple[str, ...]]: index名ごとの対象column順序.
    """
    indexes: dict[str, tuple[str, ...]] = {}
    for index in table.indexes:
        if index.name is not None:
            indexes[index.name] = tuple(column.name for column in index.columns)
    return indexes


def test_osu_direct_search_migration_creates_tables_indexes_and_rollback() -> None:
    """Migrationがsearch input, coverage, index stateを作成しrollbackできることを検証する.

    固定revisionのsourceを読み込み, beatmapsets検索入力, coverage/index state table,
    optional ParadeDB BM25 index,
    rollback時のindex/table削除がobservable schema contractとして存在することを確認する.

    Returns:
        None: osu!direct search migration source contractを検証して完了する.
    """
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260809_0100"' in migration
    assert 'down_revision: str | None = "20260713_0700"' in migration
    assert '_BEATMAPSET_TABLE = "beatmapsets"' in migration
    assert '_COVERAGE_TABLE = "beatmap_direct_coverage"' in migration
    assert '_EXTERNAL_INDEX_STATE_TABLE = "beatmap_direct_external_index_state"' in migration
    assert 'sa.Column("direct_search_text", sa.Text(), nullable=False' in migration
    assert 'sa.Column("search_document_version", sa.Integer(), nullable=False' in migration
    assert '"search_document_updated_at"' in migration
    assert "op.create_table(\n        _COVERAGE_TABLE" in migration
    assert "op.create_table(\n        _EXTERNAL_INDEX_STATE_TABLE" in migration
    assert "idx_beatmapsets_direct_search_bm25" in migration
    assert "pg_extension" in migration
    assert "if not _paradedb_extensions_created()" in migration
    assert "CREATE INDEX CONCURRENTLY" in migration
    assert "USING paradedb" in migration
    assert "WITH (key_field='id')" in migration
    for indexed_column in (
        "id",
        "direct_search_text",
    ):
        assert indexed_column in migration
    assert "op.drop_index(\n            _SEARCH_DOCUMENT_BM25_INDEX" in migration
    assert "op.drop_table(_EXTERNAL_INDEX_STATE_TABLE)" in migration
    assert "op.drop_table(_COVERAGE_TABLE)" in migration
    assert 'op.drop_column(_BEATMAPSET_TABLE, "direct_search_text")' in migration


def test_osu_direct_search_models_are_registered_for_metadata_discovery() -> None:
    """osu!direct search storage model群がBase metadataで発見可能なことを検証する.

    beatmapsets拡張列と追加modelのtable名を照合し, migration tableと同一table objectが
    observable metadataとして公開されることを確認する.

    Returns:
        None: search input model metadata discovery contractを検証して完了する.
    """
    assert BeatmapSetModel.__tablename__ == "beatmapsets"
    assert BeatmapDirectCoverageModel.__tablename__ == "beatmap_direct_coverage"
    assert (
        BeatmapDirectExternalIndexStateModel.__tablename__ == "beatmap_direct_external_index_state"
    )
    assert Base.metadata.tables["beatmapsets"] is BeatmapSetModel.__table__
    assert Base.metadata.tables["beatmap_direct_coverage"] is BeatmapDirectCoverageModel.__table__
    assert (
        Base.metadata.tables["beatmap_direct_external_index_state"]
        is BeatmapDirectExternalIndexStateModel.__table__
    )


def test_osu_direct_search_models_compile_for_postgresql() -> None:
    """PostgreSQL方言でsearch storage DDLが生成できることを検証する.

    検索入力列と長いconstraint名を含む3 tableのDDLをcompileし, migration適用前に
    PostgreSQL dialect上のschema定義エラーを検出できることを確認する.

    Returns:
        None: search storage modelのPostgreSQL DDL compileを検証して完了する.
    """
    dialect = postgresql.dialect()

    tables = (
        cast("Table", BeatmapSetModel.__table__),
        cast("Table", BeatmapDirectCoverageModel.__table__),
        cast("Table", BeatmapDirectExternalIndexStateModel.__table__),
    )
    for table in tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        if table.name == "beatmapsets":
            assert "direct_search_text TEXT DEFAULT '' NOT NULL" in ddl
            assert "search_document_version INTEGER DEFAULT '1' NOT NULL" in ddl
        for index in table.indexes:
            _ = str(CreateIndex(index).compile(dialect=dialect))


def test_beatmapset_metadata_has_direct_search_input_fields() -> None:
    """Beatmapset metadataがdirect search入力fieldを保存することを検証する.

    beatmapset table上のsource/tags/materialized text, document version, lookup indexが
    schema contractとして一致することを確認する.

    Returns:
        None: beatmapsets search input schema contractを検証して完了する.
    """
    documents = cast("Table", BeatmapSetModel.__table__)

    assert _column(documents, "id").primary_key
    for required_text_column in ("artist", "title", "creator"):
        column = _column(documents, required_text_column)
        assert not column.nullable
        assert _string_length(column) == 255
    for required_body_column in ("source", "tags", "direct_search_text"):
        assert not _column(documents, required_body_column).nullable
    assert _string_length(_column(documents, "artist_unicode")) == 255
    assert _string_length(_column(documents, "title_unicode")) == 255
    assert _checked_enum_values(_column(documents, "official_status")) == (
        "ranked",
        "approved",
        "loved",
        "qualified",
        "pending",
        "wip",
        "graveyard",
        "not_submitted",
        "unknown",
    )
    assert not _column(documents, "search_document_version").nullable
    assert not _column(documents, "search_document_updated_at").nullable
    assert {
        "ck_beatmapsets_search_document_version_positive",
    }.issubset(_check_constraint_names(documents))
    assert _indexes(documents)["idx_beatmapsets_direct_status_update"] == (
        "official_status",
        "search_document_updated_at",
        "id",
    )


def test_coverage_and_index_state_metadata_use_non_null_semantic_identity() -> None:
    """Coverageとexternal index stateがNULLに意味を持たせないscopeを使うことを検証する.

    coverage scopeとexternal index state identityを構成するcolumnがすべてNOT NULLで,
    closed valueはCHECK制約付きEnumとして保存されることを確認する.

    Returns:
        None: coverage/index state identity schema contractを検証して完了する.
    """
    coverage = cast("Table", BeatmapDirectCoverageModel.__table__)
    index_state = cast("Table", BeatmapDirectExternalIndexStateModel.__table__)

    assert _column(coverage, "id").primary_key
    for scope_column in (
        "coverage_kind",
        "source",
        "status_scope",
        "sort_key",
        "window_key",
        "from_beatmapset_id",
        "to_beatmapset_id",
    ):
        assert not _column(coverage, scope_column).nullable
    assert _checked_enum_values(_column(coverage, "coverage_kind")) == (
        "feed_window",
        "id_range",
    )
    assert _checked_enum_values(_column(coverage, "status_scope")) == (
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
    )
    assert _unique_constraints(coverage)["uq_beatmap_direct_coverage_scope"] == (
        "coverage_kind",
        "source",
        "status_scope",
        "sort_key",
        "window_key",
        "from_beatmapset_id",
        "to_beatmapset_id",
    )
    assert {
        "ck_beatmap_direct_coverage_range_non_negative",
        "ck_beatmap_direct_coverage_range_ordered",
        "ck_beatmap_direct_coverage_not_completed_and_failed",
    }.issubset(_check_constraint_names(coverage))

    assert _column(index_state, "backend").primary_key
    assert _column(index_state, "beatmapset_id").primary_key
    assert not _column(index_state, "backend").nullable
    assert not _column(index_state, "beatmapset_id").nullable
    assert _foreign_key_constraints(index_state)[
        "fk_beatmap_direct_external_index_state_beatmapset_id"
    ] == ("beatmapset_id", "beatmapsets.id")
    assert _checked_enum_values(_column(index_state, "backend")) == ("meilisearch",)
    assert _checked_enum_values(_column(index_state, "status")) == (
        "pending",
        "succeeded",
        "failed",
    )
    assert not _column(index_state, "document_version").nullable
    assert {
        "ck_beatmap_direct_index_state_version_positive",
        "ck_beatmap_direct_index_state_failure_reason",
    }.issubset(_check_constraint_names(index_state))
