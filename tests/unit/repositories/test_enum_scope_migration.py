from pathlib import Path
from typing import cast

from sqlalchemy import CheckConstraint, Column, Table, UniqueConstraint
from sqlalchemy import Enum as SQLAlchemyEnum

from osu_server.repositories.sqlalchemy.models import (
    BeatmapFetchStateModel,
    BeatmapFileAttachmentModel,
    BeatmapLeaderboardUserBestModel,
    BeatmapModel,
    BeatmapSetModel,
    BlobModel,
    ChannelModel,
    PerformanceRecalculationBatchModel,
    PerformanceRecalculationWorkItemModel,
    PersonalBestModel,
    ScoreModel,
    ScorePerformanceCalculationModel,
    ScoreSubmissionModel,
)

MIGRATION_PATH = Path(
    "alembic/versions/20260710_0400_use_enum_types_and_score_based_leaderboards.py"
)
LEADERBOARD_REPAIR_MIGRATION_PATH = Path(
    "alembic/versions/20260712_0500_repair_legacy_leaderboard_projection.py"
)
MOD_SCOPED_MIGRATION_PATH = Path(
    "alembic/versions/20260713_0600_add_mod_scoped_leaderboard_projection.py"
)
ONLINE_INDEX_MIGRATION_PATH = Path(
    "alembic/versions/20260713_0700_create_leaderboard_indexes_concurrently.py"
)


def _column(table: Table, name: str) -> Column[object]:
    return cast("Column[object]", table.c[name])


def _enum_type(table: Table, column_name: str) -> SQLAlchemyEnum:
    enum_type = _column(table, column_name).type
    assert isinstance(enum_type, SQLAlchemyEnum)
    return enum_type


def _assert_checked_string_enum(
    table: Table,
    column_name: str,
    constraint_name: str,
    length: int,
) -> None:
    enum_type = _enum_type(table, column_name)
    assert cast("bool", enum_type.native_enum) is False
    assert cast("bool", enum_type.create_constraint) is True
    assert cast("bool", enum_type.validate_strings) is True
    assert enum_type.name == constraint_name
    assert enum_type.length == length
    assert any(
        isinstance(constraint, CheckConstraint) and constraint.name == constraint_name
        for constraint in table.constraints
    )


def test_enum_migration_converts_closed_values_and_score_based_leaderboards() -> None:
    """migrationがCHECK付き文字列Enumとscore正本leaderboardを定義することを確認する.

    Returns:
        None: migration sourceの必須構造が存在することを示す.

    Raises:
        AssertionError: revision, Enum制約, またはleaderboard構造が不足する場合.

    Notes:
        PostgreSQLでの実動作はintegration migration testで別途検証する.
    """
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260710_0400"' in migration
    assert 'down_revision: str | None = "20260710_0300"' in migration
    assert 'name="ck_scores_play_time_source_known"' in migration
    assert 'name="ck_beatmaps_mode_known"' in migration
    assert 'name="ck_beatmap_fetch_states_target_type_known"' in migration
    assert 'name="ck_blobs_storage_backend_known"' in migration
    assert 'name="ck_score_submissions_state_known"' in migration
    assert "native_enum=False" in migration
    assert "create_constraint=True" in migration
    assert "sa.update(fetch_states).values(" in migration
    assert 'fetch_states.c.target_type == "beatmap"' in migration
    assert "_rebuild_current_global_projection()" in migration
    assert "beatmaps.c.checksum_md5 == scores.c.beatmap_checksum" in migration
    assert "op.execute(sa.delete(projection))" in migration
    assert 'op.drop_column("beatmap_leaderboard_user_bests", "mod_filter_key")' in migration
    assert '"leaderboard_mod_filter_keys"' not in migration
    assert "_selected_mod_filter_keys_expression(scores.c.mods)" in migration
    assert "_validate_enum_column" in migration
    assert "_create_enum_constraint" in migration
    assert "_drop_enum_constraint" in migration
    assert "postgresql.ENUM" not in migration
    assert "postgresql_using" not in migration
    assert "_ENUM_TYPES" not in migration
    assert "ck_scores_play_time_source_known" in migration
    assert "ck_score_performance_state_known" in migration


def test_mod_scoped_projection_migration_uses_checked_raw_mod_bitflags() -> None:
    """0600 migrationがraw Mod単位のprojection schemaを定義することを確認する.

    Returns:
        None: migration sourceのschema, backfill, index定義が一致したことを示す.

    Raises:
        AssertionError: revisionまたはMod単位projectionの必須構造が不足する場合.
    """
    migration = MOD_SCOPED_MIGRATION_PATH.read_text()

    assert 'revision: str = "20260713_0600"' in migration
    assert 'down_revision: str | None = "20260712_0500"' in migration
    assert 'sa.Column("mods", sa.Integer(), nullable=True)' in migration
    assert "_rebuild_projection(partition_by_mods=True)" in migration
    assert "partition_columns.append(scores.c.mods)" in migration
    assert '"ck_beatmap_leaderboard_user_bests_mods_non_negative"' in migration
    assert '["beatmap_id", "ruleset", "playstyle", "user_id", "mods"]' in migration
    assert 'op.alter_column(\n        _PROJECTION_TABLE,\n        "mods"' in migration
    assert "_rebuild_projection(partition_by_mods=False)" in migration
    assert 'op.drop_column(_PROJECTION_TABLE, "mods")' in migration
    assert "op.execute(sa.text(" not in migration


def test_leaderboard_indexes_are_created_concurrently_without_raw_sql() -> None:
    """Leaderboard index migrationがonline DDLだけを使用することを確認する.

    Returns:
        None: 0500 candidateと0700 read indexがconcurrent作成されることを示す.

    Raises:
        AssertionError: autocommit, concurrent指定, またはAlembic API利用が不足する場合.
    """
    enum_migration = MIGRATION_PATH.read_text()
    repair_migration = LEADERBOARD_REPAIR_MIGRATION_PATH.read_text()
    online_index_migration = ONLINE_INDEX_MIGRATION_PATH.read_text()

    assert '"idx_scores_beatmap_leaderboard_candidates"' not in enum_migration
    assert "with op.get_context().autocommit_block():" in repair_migration
    assert repair_migration.count("postgresql_concurrently=True") >= 2
    assert 'revision: str = "20260713_0700"' in online_index_migration
    assert 'down_revision: str | None = "20260713_0600"' in online_index_migration
    assert "with op.get_context().autocommit_block():" in online_index_migration
    assert online_index_migration.count("postgresql_concurrently=True") >= 6
    assert '"idx_scores_beatmap_leaderboard_candidates"' in online_index_migration
    assert '"idx_beatmap_leaderboard_user_bests_global_rank"' in online_index_migration
    assert '"idx_beatmap_leaderboard_user_bests_mod_rank"' in online_index_migration
    assert "op.execute(sa.text(" not in repair_migration
    assert "op.execute(sa.text(" not in online_index_migration


def test_current_models_use_checked_string_enums_for_closed_value_columns() -> None:
    """閉集合カラムが非native Enumと名前付きCHECKを使用することを検証する.

    Returns:
        None: 全対象カラムの型と制約を検証したことを示す.

    Raises:
        AssertionError: native Enum、CHECK未作成、または制約名不一致の場合.
    """
    cases = (
        (ChannelModel.__table__, "channel_type", "ck_channels_channel_type_known", 16),
        (ScoreModel.__table__, "grade", "ck_scores_grade_known", 2),
        (
            ScoreModel.__table__,
            "beatmap_status_at_submission",
            "ck_beatmap_rank_status_known",
            32,
        ),
        (
            ScoreModel.__table__,
            "play_time_source",
            "ck_scores_play_time_source_known",
            32,
        ),
        (
            ScoreSubmissionModel.__table__,
            "state",
            "ck_score_submissions_state_known",
            32,
        ),
        (
            BeatmapSetModel.__table__,
            "official_status",
            "ck_beatmap_rank_status_known",
            32,
        ),
        (
            BeatmapSetModel.__table__,
            "official_status_source",
            "ck_beatmap_metadata_source_known",
            64,
        ),
        (BeatmapModel.__table__, "mode", "ck_beatmaps_mode_known", 16),
        (
            BeatmapModel.__table__,
            "official_status",
            "ck_beatmap_rank_status_known",
            32,
        ),
        (
            BeatmapModel.__table__,
            "official_status_source",
            "ck_beatmap_metadata_source_known",
            64,
        ),
        (
            BeatmapModel.__table__,
            "local_status_override",
            "ck_beatmaps_local_status_override_known",
            32,
        ),
        (
            BeatmapFileAttachmentModel.__table__,
            "source",
            "ck_beatmap_file_attachments_source_known",
            32,
        ),
        (
            BeatmapFetchStateModel.__table__,
            "target_type",
            "ck_beatmap_fetch_states_target_type_known",
            32,
        ),
        (
            BeatmapFetchStateModel.__table__,
            "status",
            "ck_beatmap_fetch_states_status_known",
            32,
        ),
        (BlobModel.__table__, "storage_backend", "ck_blobs_storage_backend_known", 32),
        (
            PersonalBestModel.__table__,
            "category",
            "ck_personal_bests_category_known",
            32,
        ),
        (
            ScorePerformanceCalculationModel.__table__,
            "state",
            "ck_score_performance_state_known",
            32,
        ),
        (
            ScorePerformanceCalculationModel.__table__,
            "formula_profile",
            "ck_formula_profile_known",
            64,
        ),
        (
            PerformanceRecalculationBatchModel.__table__,
            "status",
            "ck_performance_recalculation_batches_status_known",
            32,
        ),
        (
            PerformanceRecalculationBatchModel.__table__,
            "target_formula_profile",
            "ck_formula_profile_known",
            64,
        ),
        (
            PerformanceRecalculationWorkItemModel.__table__,
            "reason",
            "ck_performance_recalculation_work_items_reason_known",
            64,
        ),
        (
            PerformanceRecalculationWorkItemModel.__table__,
            "state",
            "ck_performance_recalculation_work_items_state_known",
            32,
        ),
    )

    for table, column_name, constraint_name, length in cases:
        _assert_checked_string_enum(
            cast("Table", table),
            column_name,
            constraint_name,
            length,
        )


def test_current_leaderboard_projection_is_mod_scoped_and_score_unique() -> None:
    table = cast("Table", BeatmapLeaderboardUserBestModel.__table__)
    unique_constraints = {
        constraint.name: constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "mod_filter_key" not in table.c
    assert not _column(table, "mods").nullable
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
