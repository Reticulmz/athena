from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy import Column, Table, UniqueConstraint

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

if TYPE_CHECKING:
    from sqlalchemy.dialects.postgresql import ENUM

MIGRATION_PATH = Path(
    "alembic/versions/20260710_0400_use_enum_types_and_score_based_leaderboards.py"
)


def _column(table: Table, name: str) -> Column[object]:
    return cast("Column[object]", table.c[name])


def _enum_name(table: Table, column_name: str) -> str:
    return str(cast("ENUM", _column(table, column_name).type).name)


def test_enum_migration_converts_closed_values_and_score_based_leaderboards() -> None:
    """migrationがEnum変換とscore正本leaderboardを定義することを確認する.

    Returns:
        None: migration sourceの必須構造が存在することを示す.

    Raises:
        AssertionError: revision, Enum変換, またはleaderboard構造が不足する場合.

    Notes:
        PostgreSQLでの実動作はintegration migration testで別途検証する.
    """
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260710_0400"' in migration
    assert 'down_revision: str | None = "20260710_0300"' in migration
    assert 'name="play_time_source"' in migration
    assert 'name="beatmap_mode"' in migration
    assert 'name="beatmap_fetch_target_kind"' in migration
    assert 'name="blob_storage_backend"' in migration
    assert 'name="score_submission_state"' in migration
    assert "sa.update(fetch_states).values(" in migration
    assert 'fetch_states.c.target_type == "beatmap"' in migration
    assert "_rebuild_current_global_projection()" in migration
    assert "beatmaps.c.checksum_md5 == scores.c.beatmap_checksum" in migration
    assert "op.execute(sa.delete(projection))" in migration
    assert 'op.drop_column("beatmap_leaderboard_user_bests", "mod_filter_key")' in migration
    assert '"leaderboard_mod_filter_keys"' not in migration
    assert "_selected_mod_filter_keys_expression(scores.c.mods)" in migration
    assert "_validate_enum_column" in migration
    assert (
        '"play_time_source",\n        sa.String(length=32),\n        PLAY_TIME_SOURCE_ENUM,'
        in migration
    )
    assert 'postgresql_using=f"{column_name}::text::{enum_name}"' in migration
    assert "ck_scores_play_time_source_known" in migration
    assert "ck_score_performance_state_known" in migration


def test_current_models_use_postgresql_enums_for_closed_value_columns() -> None:
    assert _enum_name(cast("Table", ChannelModel.__table__), "channel_type") == "channel_type"
    assert _enum_name(cast("Table", ScoreModel.__table__), "grade") == "score_grade"
    assert (
        _enum_name(cast("Table", ScoreModel.__table__), "play_time_source") == "play_time_source"
    )
    assert (
        _enum_name(cast("Table", ScoreSubmissionModel.__table__), "state")
        == "score_submission_state"
    )
    assert (
        _enum_name(cast("Table", BeatmapSetModel.__table__), "official_status")
        == "beatmap_rank_status"
    )
    assert (
        _enum_name(cast("Table", BeatmapModel.__table__), "official_status_source")
        == "beatmap_metadata_source"
    )
    assert _enum_name(cast("Table", BeatmapModel.__table__), "mode") == "beatmap_mode"
    assert (
        _enum_name(cast("Table", BeatmapFileAttachmentModel.__table__), "source")
        == "beatmap_file_source"
    )
    assert (
        _enum_name(cast("Table", BeatmapFetchStateModel.__table__), "target_type")
        == "beatmap_fetch_target_kind"
    )
    assert (
        _enum_name(cast("Table", BeatmapFetchStateModel.__table__), "status")
        == "beatmap_fetch_state"
    )
    assert (
        _enum_name(cast("Table", BlobModel.__table__), "storage_backend") == "blob_storage_backend"
    )
    assert (
        _enum_name(cast("Table", PersonalBestModel.__table__), "category")
        == "leaderboard_category"
    )
    assert (
        _enum_name(cast("Table", ScorePerformanceCalculationModel.__table__), "state")
        == "performance_calculation_state"
    )
    assert (
        _enum_name(cast("Table", PerformanceRecalculationBatchModel.__table__), "status")
        == "performance_recalculation_batch_status"
    )
    assert (
        _enum_name(cast("Table", PerformanceRecalculationWorkItemModel.__table__), "reason")
        == "performance_recalculation_reason"
    )


def test_current_leaderboard_projection_has_single_global_scope_and_unique_score() -> None:
    table = cast("Table", BeatmapLeaderboardUserBestModel.__table__)
    unique_constraints = {
        constraint.name: constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "mod_filter_key" not in table.c
    unique_scope = unique_constraints["uq_beatmap_leaderboard_user_bests_scope"]
    assert tuple(column.name for column in unique_scope.columns) == (
        "beatmap_id",
        "ruleset",
        "playstyle",
        "user_id",
    )
    unique_score = unique_constraints["uq_beatmap_leaderboard_user_bests_score_id"]
    assert tuple(column.name for column in unique_score.columns) == ("score_id",)
