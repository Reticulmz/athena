from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy import Column, Table

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
    "alembic/versions/20260710_0100_use_enum_types_and_explicit_leaderboard_scope.py"
)


def _column(table: Table, name: str) -> Column[object]:
    return cast("Column[object]", table.c[name])


def _enum_name(table: Table, column_name: str) -> str:
    return str(cast("ENUM", _column(table, column_name).type).name)


def test_enum_scope_migration_converts_closed_value_columns_and_leaderboard_scope() -> None:
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260710_0100"' in migration
    assert 'down_revision: str | None = "20260630_0300"' in migration
    assert 'name="play_time_source"' in migration
    assert 'name="beatmap_mode"' in migration
    assert 'name="beatmap_fetch_target_kind"' in migration
    assert 'name="blob_storage_backend"' in migration
    assert 'name="score_submission_state"' in migration
    assert "target_type = CASE target_type" in migration
    assert "WHEN 'beatmap' THEN 'metadata:beatmap'" in migration
    assert "SET mod_filter_key = -1" in migration
    assert "WHERE mod_filter_key IS NULL" in migration
    assert "SET mode = 'unknown'" in migration
    assert "mod_filter_key >= -1" in migration
    assert 'postgresql_using="play_time_source::text::play_time_source"' in migration
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


def test_current_leaderboard_projection_scope_is_not_nullable() -> None:
    table = cast("Table", BeatmapLeaderboardUserBestModel.__table__)
    unique_scope_index = next(
        index
        for index in table.indexes
        if index.name == "idx_beatmap_leaderboard_user_bests_scope_unique"
    )

    assert not _column(table, "mod_filter_key").nullable
    assert tuple(column.name for column in unique_scope_index.columns) == (
        "beatmap_id",
        "ruleset",
        "playstyle",
        "user_id",
        "mod_filter_key",
    )
