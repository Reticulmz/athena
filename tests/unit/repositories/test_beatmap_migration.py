"""Beatmap mirror migrationのschemaとmetadata contractを検証する."""

from pathlib import Path
from typing import cast

from sqlalchemy import Column, ForeignKeyConstraint, String, Table, UniqueConstraint

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models import (
    BeatmapFetchStateModel,
    BeatmapFileAttachmentModel,
    BeatmapModel,
    BeatmapSetModel,
)

MIGRATION_PATH = Path("alembic/versions/20260604_2001_create_beatmap_mirror_tables.py")


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


def _string_length(column: Column[object]) -> int | None:
    """String columnの宣言済み最大長を取得する.

    Args:
        column (Column[object]): String型であることを前提にしたcolumn.

    Returns:
        int | None: String型に設定された最大長. 長さ未指定時はNone.
    """
    return cast("String", column.type).length


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


def test_beatmap_migration_creates_tables_and_core_constraints() -> None:
    """Beatmap mirror migrationがcore tableとidentity constraintを作成することを検証する.

    固定revisionのsourceを読み込み, beatmapset, beatmap, attachment, fetch state tableとunique,
    foreign key, blob metadata分離がobservable contractとして存在することを確認する.

    Returns:
        None: beatmap mirror migration schema contractを検証して完了する.
    """
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260604_2001"' in migration
    assert 'down_revision: str | None = "20260604_1846"' in migration
    assert 'op.create_table(\n        "beatmapsets"' in migration
    assert 'op.create_table(\n        "beatmaps"' in migration
    assert 'op.create_table(\n        "beatmap_file_attachments"' in migration
    assert 'op.create_table(\n        "beatmap_fetch_states"' in migration
    assert 'sa.UniqueConstraint("checksum_md5", name="uq_beatmaps_checksum_md5")' in migration
    assert '"beatmap_id",' in migration
    assert '"checksum_md5",' in migration
    assert 'name="uq_beatmap_file_attachments_beatmap_checksum_md5"' in migration
    assert (
        'sa.UniqueConstraint("target_type", "target_key", name="uq_beatmap_fetch_states_target")'
    ) in migration
    assert 'sa.ForeignKey("blobs.id")' in migration
    assert "body" not in migration
    assert "content_bytes" not in migration
    assert "osu_body" not in migration


def test_beatmap_migration_creates_lookup_indexes_and_downgrade() -> None:
    """Beatmap mirror migrationがlookup indexと完全なdowngradeを定義することを検証する.

    固定revisionのsourceを読み込み, mirror lookup indexと依存順序に沿うtable dropが
    observable contractとして存在することを確認する.

    Returns:
        None: beatmap mirror lookupとdowngrade contractを検証して完了する.
    """
    migration = MIGRATION_PATH.read_text()

    assert (
        'op.create_index("idx_beatmaps_beatmapset_id", "beatmaps", ["beatmapset_id"])' in migration
    )
    assert (
        'op.create_index("idx_beatmaps_checksum_md5", "beatmaps", ["checksum_md5"])' in migration
    )
    assert '"idx_beatmap_file_attachments_beatmap"' in migration
    assert '"beatmap_file_attachments", ["beatmap_id"]' in migration
    assert '"idx_beatmap_fetch_states_target_lookup"' in migration
    assert '"beatmap_fetch_states",' in migration
    assert '["target_type", "target_key", "status"]' in migration
    assert 'op.drop_table("beatmap_fetch_states")' in migration
    assert 'op.drop_table("beatmap_file_attachments")' in migration
    assert 'op.drop_table("beatmaps")' in migration
    assert 'op.drop_table("beatmapsets")' in migration


def test_beatmap_models_are_registered_for_metadata_discovery() -> None:
    """Beatmap mirror model群がBase metadataで発見可能なことを検証する.

    各modelのtable名とBase.metadataの登録先を照合し, migration tableと同一table objectが
    observable metadataとして公開されることを確認する.

    Returns:
        None: beatmap mirror metadata discovery contractを検証して完了する.
    """
    assert BeatmapSetModel.__tablename__ == "beatmapsets"
    assert BeatmapModel.__tablename__ == "beatmaps"
    assert BeatmapFileAttachmentModel.__tablename__ == "beatmap_file_attachments"
    assert BeatmapFetchStateModel.__tablename__ == "beatmap_fetch_states"
    assert Base.metadata.tables["beatmapsets"] is BeatmapSetModel.__table__
    assert Base.metadata.tables["beatmaps"] is BeatmapModel.__table__
    assert Base.metadata.tables["beatmap_file_attachments"] is BeatmapFileAttachmentModel.__table__
    assert Base.metadata.tables["beatmap_fetch_states"] is BeatmapFetchStateModel.__table__


def test_beatmap_model_metadata_matches_mirror_identity_contract() -> None:
    """BeatmapModel metadataがmirror identity contractを満たすことを検証する.

    現行beatmap tableを条件に, primary key, required source identity, status metadata,
    beatmapset foreign key, lookup indexがobservable metadataとして一致することを確認する.

    Returns:
        None: beatmap mirror identity metadata contractを検証して完了する.
    """
    beatmaps = cast("Table", BeatmapModel.__table__)
    beatmapsets = cast("Table", BeatmapSetModel.__table__)

    assert _column(beatmapsets, "id").primary_key
    assert _column(beatmaps, "id").primary_key
    assert not _column(beatmaps, "beatmapset_id").nullable
    assert _string_length(_column(beatmaps, "checksum_md5")) == 32
    assert not _column(beatmaps, "mode").nullable
    assert not _column(beatmaps, "version").nullable
    assert not _column(beatmaps, "official_status").nullable
    assert not _column(beatmaps, "official_status_source").nullable
    assert not _column(beatmaps, "official_status_verified").nullable
    assert "local_status_override" in beatmaps.columns
    assert "last_fetched_at" in beatmaps.columns
    assert "next_refresh_at" in beatmaps.columns
    assert _foreign_key_constraints(beatmaps)["fk_beatmaps_beatmapset_id"] == (
        "beatmapset_id",
        "beatmapsets.id",
    )
    assert _unique_constraints(beatmaps)["uq_beatmaps_checksum_md5"] == ("checksum_md5",)
    assert _indexes(beatmaps)["idx_beatmaps_beatmapset_id"] == ("beatmapset_id",)
    assert _indexes(beatmaps)["idx_beatmaps_checksum_md5"] == ("checksum_md5",)


def test_file_attachment_and_fetch_state_metadata_match_idempotency_contract() -> None:
    """Attachmentとfetch state metadataがidempotency contractを満たすことを検証する.

    現行attachmentとfetch state tableを条件に, checksum identity, blob reference, target scope,
    status lookup indexがobservable metadataとして一致することを確認する.

    Returns:
        None: attachmentとfetch state idempotency contractを検証して完了する.
    """
    attachments = cast("Table", BeatmapFileAttachmentModel.__table__)
    fetch_states = cast("Table", BeatmapFetchStateModel.__table__)

    assert not _column(attachments, "beatmap_id").nullable
    assert not _column(attachments, "blob_id").nullable
    assert not _column(attachments, "checksum_md5").nullable
    assert _string_length(_column(attachments, "checksum_md5")) == 32
    assert _string_length(_column(attachments, "verified_md5")) == 32
    assert {"body", "content_bytes", "osu_body"}.isdisjoint(attachments.columns)
    assert _foreign_key_constraints(attachments)["fk_beatmap_file_attachments_beatmap_id"] == (
        "beatmap_id",
        "beatmaps.id",
    )
    assert _foreign_key_constraints(attachments)["fk_beatmap_file_attachments_blob_id"] == (
        "blob_id",
        "blobs.id",
    )
    assert _unique_constraints(attachments)[
        "uq_beatmap_file_attachments_beatmap_checksum_md5"
    ] == ("beatmap_id", "checksum_md5")
    assert _indexes(attachments)["idx_beatmap_file_attachments_beatmap"] == ("beatmap_id",)

    assert not _column(fetch_states, "target_type").nullable
    assert not _column(fetch_states, "target_key").nullable
    assert not _column(fetch_states, "status").nullable
    assert not _column(fetch_states, "attempt_count").nullable
    assert _unique_constraints(fetch_states)["uq_beatmap_fetch_states_target"] == (
        "target_type",
        "target_key",
    )
    assert _indexes(fetch_states)["idx_beatmap_fetch_states_target_lookup"] == (
        "target_type",
        "target_key",
        "status",
    )
