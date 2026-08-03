"""Beatmap leaderboard migrationのschemaとmetadata contractを検証する."""

from typing import cast

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    Table,
    UniqueConstraint,
)

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models import BeatmapLeaderboardUserBestModel, ScoreModel
from tests.support.paths import ALEMBIC_VERSIONS_ROOT

MIGRATION_PATH = ALEMBIC_VERSIONS_ROOT / "20260618_0100_add_beatmap_leaderboard_projection.py"


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


def _check_constraints(table: Table) -> set[str]:
    """Tableに定義されたCHECK constraint名を収集する.

    Args:
        table (Table): CHECK constraintを検証するSQLAlchemy table metadata.

    Returns:
        set[str]: tableに登録されたCHECK constraint名の集合.
    """
    return {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


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


def _indexes(table: Table) -> dict[str, Index]:
    """Tableの名前付きindexをindex object対応表へ変換する.

    Args:
        table (Table): indexを検証するSQLAlchemy table metadata.

    Returns:
        dict[str, Index]: index名ごとのSQLAlchemy Index object.
    """
    indexes: dict[str, Index] = {}
    for index in table.indexes:
        if index.name is not None:
            indexes[cast("str", index.name)] = index
    return indexes


def _unique_constraints(table: Table) -> dict[str, UniqueConstraint]:
    """Tableの名前付きunique constraintをobject対応表へ変換する.

    Args:
        table (Table): unique constraintを検証するSQLAlchemy table metadata.

    Returns:
        dict[str, UniqueConstraint]: constraint名ごとのSQLAlchemy UniqueConstraint object.
    """
    return {
        cast("str", constraint.name): constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name is not None
    }


def _index_columns(index: Index) -> tuple[str, ...]:
    """Indexに登録されたcolumn名を宣言順に取得する.

    Args:
        index (Index): column順序を検証するSQLAlchemy index.

    Returns:
        tuple[str, ...]: indexに登録されたcolumn名の宣言順tuple.
    """
    return tuple(column.name for column in index.columns)


def test_beatmap_leaderboard_migration_adds_score_eligibility_and_projection_schema() -> None:
    """Leaderboard migrationがsubmission eligibilityとprojection schemaを追加することを検証する.

    固定revisionのsourceを読み込み, score eligibility snapshot, projection table, rank ordering,
    legacy table保持, downgrade operationがobservable contractとして存在することを確認する.

    Returns:
        None: leaderboard migration schema contractを検証して完了する.
    """
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260618_0100"' in migration
    assert 'down_revision: str | None = "20260617_0102"' in migration
    assert '"leaderboard_eligible_at_submission"' in migration
    assert 'server_default=sa.text("false")' in migration
    assert "beatmap_status_at_submission IN (" in migration
    assert "'ranked', 'approved', 'loved', 'qualified'" in migration
    assert 'op.create_table(\n        "beatmap_leaderboard_user_bests"' in migration
    assert "fk_beatmap_leaderboard_user_bests_score_id" in migration
    assert "ck_beatmap_leaderboard_user_bests_mod_filter_key_non_negative" in migration
    assert "idx_beatmap_leaderboard_user_bests_scope_unique" in migration
    assert "COALESCE(mod_filter_key, -1)" in migration
    assert "idx_beatmap_leaderboard_user_bests_ordering" in migration
    assert "score DESC" in migration
    assert "submitted_at ASC" in migration
    assert "score_id ASC" in migration
    assert "idx_beatmap_leaderboard_user_bests_user_rebuild" in migration
    assert "idx_scores_leaderboard_rebuild_candidate" in migration
    assert 'op.drop_table("personal_bests")' not in migration
    assert 'op.drop_table("beatmap_leaderboard_user_bests")' in migration
    assert 'op.drop_column("scores", "leaderboard_eligible_at_submission")' in migration


def test_legacy_personal_bests_migrate_to_all_mods_projection_from_source_scores() -> None:
    """Legacy personal bestがsource scoreからall-mods projectionへ移行することを検証する.

    固定revisionのsourceを読み込み, eligible source score, all-mods scope,
    deterministic rank orderとwindow functionが含まれるobservable migration behaviorを確認する.

    Returns:
        None: legacy personal best backfill contractを検証して完了する.
    """
    migration = MIGRATION_PATH.read_text()

    assert "INSERT INTO beatmap_leaderboard_user_bests" in migration
    assert "FROM personal_bests pb" in migration
    assert "INNER JOIN scores s ON s.id = pb.score_id" in migration
    assert "pb.category IN ('global', 'country', 'friends')" in migration
    assert "s.leaderboard_eligible_at_submission = true" in migration
    assert "s.id AS score_id" in migration
    assert "s.score AS score" in migration
    assert "s.submitted_at AS submitted_at" in migration
    assert "NULL::integer AS mod_filter_key" in migration
    assert "ROW_NUMBER() OVER" in migration
    assert "ORDER BY s.score DESC, s.submitted_at ASC, s.id ASC" in migration


def test_legacy_personal_best_source_missing_skips_are_observable() -> None:
    """Missing source scoreのlegacy personal best skipが観測可能なことを検証する.

    固定revisionのsourceを読み込み, LEFT JOINでsource missingを検出し, NOTICEとして記録する
    observable outcomeを確認する.

    Returns:
        None: source missing skip observability contractを検証して完了する.
    """
    migration = MIGRATION_PATH.read_text()

    assert "beatmap_leaderboard_legacy_personal_best_skipped" in migration
    assert "source_missing" in migration
    assert "LEFT JOIN scores s ON s.id = pb.score_id" in migration
    assert "WHERE s.id IS NULL" in migration
    assert "RAISE NOTICE" in migration


def test_legacy_personal_bests_do_not_seed_selected_mods_projection() -> None:
    """Legacy personal best backfillがselected-mods projectionをseedしないことを検証する.

    固定revisionのsourceを読み込み, all-modsを表すNULL scopeだけを使用し, selected mods由来の
    filter keyを使用しないobservable outcomeを確認する.

    Returns:
        None: all-mods migration scope contractを検証して完了する.
    """
    migration = MIGRATION_PATH.read_text()

    assert "NULL::integer AS mod_filter_key" in migration
    assert "mod_filter_key = " not in migration
    assert "s.mods AS mod_filter_key" not in migration
    assert "'selected_mods'" not in migration


def test_beatmap_leaderboard_model_is_registered_for_metadata_discovery() -> None:
    """Leaderboard projection modelがBase metadataで発見可能なことを検証する.

    modelのtable名とBase.metadataの登録先を照合し, projection tableと同一table object,
    score eligibility columnがobservable metadataとして公開されることを確認する.

    Returns:
        None: leaderboard metadata discovery contractを検証して完了する.
    """
    assert BeatmapLeaderboardUserBestModel.__tablename__ == "beatmap_leaderboard_user_bests"
    assert (
        Base.metadata.tables["beatmap_leaderboard_user_bests"]
        is BeatmapLeaderboardUserBestModel.__table__
    )
    assert "leaderboard_eligible_at_submission" in ScoreModel.__table__.columns


def test_score_metadata_includes_submission_time_leaderboard_eligibility() -> None:
    """Score metadataがsubmission時leaderboard eligibilityを保持することを検証する.

    現行score tableを条件に, non-null Boolean snapshot, server default, rebuild candidate index,
    obsolete mod filter index不在がobservable metadataとして一致することを確認する.

    Returns:
        None: score leaderboard eligibility metadata contractを検証して完了する.
    """
    table = cast("Table", ScoreModel.__table__)

    eligibility_column = _column(table, "leaderboard_eligible_at_submission")
    assert isinstance(eligibility_column.type, Boolean)
    assert not eligibility_column.nullable
    assert eligibility_column.server_default is not None

    rebuild_index = _indexes(table)["idx_scores_leaderboard_rebuild_candidate"]
    assert _index_columns(rebuild_index) == (
        "beatmap_id",
        "ruleset",
        "playstyle",
        "user_id",
        "leaderboard_eligible_at_submission",
        "passed",
        "score",
        "submitted_at",
        "id",
    )
    assert rebuild_index.unique is False

    assert "leaderboard_mod_filter_keys" not in table.c
    assert "idx_scores_beatmap_leaderboard_candidates" in _indexes(table)
    assert "idx_scores_leaderboard_mod_filter_keys" not in _indexes(table)


def test_projection_metadata_matches_scope_and_rank_key_contract() -> None:
    """Projection metadataがmod scopeとrank key contractを満たすことを検証する.

    現行projection tableを条件に, required scope, score identity, CHECK constraint, globalとmod
    rank indexがobservable metadataとして一致することを確認する.

    Returns:
        None: leaderboard projection metadata contractを検証して完了する.
    """
    table = cast("Table", BeatmapLeaderboardUserBestModel.__table__)

    assert _column(table, "id").primary_key
    assert not _column(table, "beatmap_id").nullable
    assert not _column(table, "ruleset").nullable
    assert not _column(table, "playstyle").nullable
    assert not _column(table, "user_id").nullable
    assert "mod_filter_key" not in table.c
    assert not _column(table, "mods").nullable
    assert not _column(table, "score_id").nullable
    assert not _column(table, "score").nullable
    assert not _column(table, "submitted_at").nullable
    assert not _column(table, "created_at").nullable
    assert not _column(table, "updated_at").nullable
    assert _foreign_key_constraints(table)["fk_beatmap_leaderboard_user_bests_score_id"] == (
        "score_id",
        "scores.id",
    )
    assert "ck_beatmap_leaderboard_user_bests_mods_non_negative" in _check_constraints(table)

    unique_constraints = _unique_constraints(table)
    unique_scope = unique_constraints["uq_beatmap_leaderboard_user_bests_scope"]
    assert tuple(column.name for column in unique_scope.columns) == (
        "beatmap_id",
        "ruleset",
        "playstyle",
        "user_id",
        "mods",
    )
    unique_score = unique_constraints["uq_beatmap_leaderboard_user_bests_score_id"]
    assert tuple(column.name for column in unique_score.columns) == ("score_id",)

    indexes = _indexes(table)
    assert "idx_beatmap_leaderboard_user_bests_ordering" not in indexes
    user_rebuild_index = indexes["idx_beatmap_leaderboard_user_bests_user_rebuild"]
    assert user_rebuild_index.unique is False
    assert _index_columns(user_rebuild_index) == (
        "user_id",
        "beatmap_id",
        "ruleset",
        "playstyle",
    )
    global_rank_index = indexes["idx_beatmap_leaderboard_user_bests_global_rank"]
    assert global_rank_index.unique is False
    assert _index_columns(global_rank_index) == (
        "beatmap_id",
        "ruleset",
        "playstyle",
        "beatmap_checksum",
        "user_id",
        "score",
        "submitted_at",
        "score_id",
    )
    mod_rank_index = indexes["idx_beatmap_leaderboard_user_bests_mod_rank"]
    assert mod_rank_index.unique is False
    assert _index_columns(mod_rank_index) == (
        "beatmap_id",
        "ruleset",
        "playstyle",
        "beatmap_checksum",
        "mods",
        "user_id",
        "score",
        "submitted_at",
        "score_id",
    )
