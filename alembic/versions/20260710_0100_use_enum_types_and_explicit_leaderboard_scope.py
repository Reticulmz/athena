"""Use enum types and explicit leaderboard scopes.

Revision ID: 20260710_0100
Revises: 20260630_0300
Create Date: 2026-07-10 01:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260710_0100"
down_revision: str | None = "20260630_0300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BEATMAP_FETCH_STATE_ENUM = postgresql.ENUM(
    "fresh",
    "stale",
    "pending_fetch",
    "failed",
    name="beatmap_fetch_state",
)
BEATMAP_FETCH_TARGET_KIND_ENUM = postgresql.ENUM(
    "metadata:beatmap",
    "metadata:beatmapset",
    "metadata:checksum",
    "file:beatmap",
    name="beatmap_fetch_target_kind",
)
BEATMAP_FILE_SOURCE_ENUM = postgresql.ENUM(
    "official",
    "legacy_official",
    "mirror",
    "osu_current",
    "osu_legacy",
    "community_mirror",
    "archive_extracted",
    name="beatmap_file_source",
)
BEATMAP_METADATA_SOURCE_ENUM = postgresql.ENUM(
    "official",
    "legacy_official",
    "mirror",
    name="beatmap_metadata_source",
)
BEATMAP_MODE_ENUM = postgresql.ENUM(
    "osu",
    "taiko",
    "fruits",
    "mania",
    "unknown",
    name="beatmap_mode",
)
BEATMAP_RANK_STATUS_ENUM = postgresql.ENUM(
    "ranked",
    "approved",
    "loved",
    "qualified",
    "pending",
    "wip",
    "graveyard",
    "not_submitted",
    "unknown",
    name="beatmap_rank_status",
)
BLOB_STORAGE_BACKEND_ENUM = postgresql.ENUM(
    "local",
    "s3",
    name="blob_storage_backend",
)
CHANNEL_TYPE_ENUM = postgresql.ENUM(
    "public",
    "multiplayer",
    "spectator",
    "temporary",
    name="channel_type",
)
FORMULA_PROFILE_ENUM = postgresql.ENUM(
    "vanilla_ranked_legacy",
    "vanilla_ranked_v1",
    name="formula_profile",
)
LEADERBOARD_CATEGORY_ENUM = postgresql.ENUM(
    "global",
    "country",
    "selected_mods",
    "friends",
    name="leaderboard_category",
)
LOCAL_BEATMAP_STATUS_ENUM = postgresql.ENUM(
    "ranked",
    "loved",
    "qualified",
    "pending",
    "wip",
    "graveyard",
    "not_submitted",
    "unknown",
    name="local_beatmap_status",
)
PERFORMANCE_CALCULATION_STATE_ENUM = postgresql.ENUM(
    "queued",
    "fetching_file",
    "calculating",
    "completed",
    "unavailable",
    "superseded",
    name="performance_calculation_state",
)
PERFORMANCE_RECALCULATION_BATCH_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "running",
    "completed",
    name="performance_recalculation_batch_status",
)
PERFORMANCE_RECALCULATION_REASON_ENUM = postgresql.ENUM(
    "uncalculated",
    "stale",
    "calculator_version_mismatch",
    "formula_profile_mismatch",
    "unavailable",
    name="performance_recalculation_reason",
)
PERFORMANCE_RECALCULATION_WORK_ITEM_STATE_ENUM = postgresql.ENUM(
    "pending",
    "claimed",
    "completed",
    "unavailable",
    name="performance_recalculation_work_item_state",
)
PLAY_TIME_SOURCE_ENUM = postgresql.ENUM(
    "fail_time",
    "beatmap_total_length",
    name="play_time_source",
)
SCORE_GRADE_ENUM = postgresql.ENUM("XH", "X", "SH", "S", "A", "B", "C", "D", name="score_grade")
SCORE_SUBMISSION_STATE_ENUM = postgresql.ENUM(
    "received",
    "processing",
    "completed",
    "terminal_rejected",
    "retryable",
    name="score_submission_state",
)

_ENUM_TYPES = (
    BEATMAP_FETCH_STATE_ENUM,
    BEATMAP_FETCH_TARGET_KIND_ENUM,
    BEATMAP_FILE_SOURCE_ENUM,
    BEATMAP_METADATA_SOURCE_ENUM,
    BEATMAP_MODE_ENUM,
    BEATMAP_RANK_STATUS_ENUM,
    BLOB_STORAGE_BACKEND_ENUM,
    CHANNEL_TYPE_ENUM,
    FORMULA_PROFILE_ENUM,
    LEADERBOARD_CATEGORY_ENUM,
    LOCAL_BEATMAP_STATUS_ENUM,
    PERFORMANCE_CALCULATION_STATE_ENUM,
    PERFORMANCE_RECALCULATION_BATCH_STATUS_ENUM,
    PERFORMANCE_RECALCULATION_REASON_ENUM,
    PERFORMANCE_RECALCULATION_WORK_ITEM_STATE_ENUM,
    PLAY_TIME_SOURCE_ENUM,
    SCORE_GRADE_ENUM,
    SCORE_SUBMISSION_STATE_ENUM,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in _ENUM_TYPES:
        enum_type.create(bind, checkfirst=True)

    _upgrade_leaderboard_scope()
    _upgrade_score_enums()
    _upgrade_beatmap_enums()
    _upgrade_blob_enums()
    _upgrade_channel_enums()
    _upgrade_personal_best_enums()
    _upgrade_performance_enums()


def downgrade() -> None:
    _downgrade_performance_enums()
    _downgrade_personal_best_enums()
    _downgrade_channel_enums()
    _downgrade_blob_enums()
    _downgrade_beatmap_enums()
    _downgrade_score_enums()
    _downgrade_leaderboard_scope()

    bind = op.get_bind()
    for enum_type in reversed(_ENUM_TYPES):
        enum_type.drop(bind, checkfirst=True)


def _upgrade_leaderboard_scope() -> None:
    op.drop_index(
        "idx_beatmap_leaderboard_user_bests_scope_unique",
        table_name="beatmap_leaderboard_user_bests",
    )
    op.drop_index(
        "idx_beatmap_leaderboard_user_bests_ordering",
        table_name="beatmap_leaderboard_user_bests",
    )
    op.drop_constraint(
        "ck_beatmap_leaderboard_user_bests_mod_filter_key_non_negative",
        "beatmap_leaderboard_user_bests",
        type_="check",
    )
    op.execute(
        sa.text(
            """
            UPDATE beatmap_leaderboard_user_bests
            SET mod_filter_key = -1
            WHERE mod_filter_key IS NULL
            """
        )
    )
    op.alter_column(
        "beatmap_leaderboard_user_bests",
        "mod_filter_key",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_beatmap_leaderboard_user_bests_mod_filter_key_scope",
        "beatmap_leaderboard_user_bests",
        "mod_filter_key >= -1",
    )
    op.create_index(
        "idx_beatmap_leaderboard_user_bests_scope_unique",
        "beatmap_leaderboard_user_bests",
        ["beatmap_id", "ruleset", "playstyle", "user_id", "mod_filter_key"],
        unique=True,
    )
    op.create_index(
        "idx_beatmap_leaderboard_user_bests_ordering",
        "beatmap_leaderboard_user_bests",
        [
            "beatmap_id",
            "ruleset",
            "playstyle",
            "mod_filter_key",
            sa.text("score DESC"),
            sa.text("submitted_at ASC"),
            sa.text("score_id ASC"),
        ],
    )


def _downgrade_leaderboard_scope() -> None:
    op.drop_index(
        "idx_beatmap_leaderboard_user_bests_ordering",
        table_name="beatmap_leaderboard_user_bests",
    )
    op.drop_index(
        "idx_beatmap_leaderboard_user_bests_scope_unique",
        table_name="beatmap_leaderboard_user_bests",
    )
    op.drop_constraint(
        "ck_beatmap_leaderboard_user_bests_mod_filter_key_scope",
        "beatmap_leaderboard_user_bests",
        type_="check",
    )
    op.alter_column(
        "beatmap_leaderboard_user_bests",
        "mod_filter_key",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.execute(
        sa.text(
            """
            UPDATE beatmap_leaderboard_user_bests
            SET mod_filter_key = NULL
            WHERE mod_filter_key = -1
            """
        )
    )
    op.create_check_constraint(
        "ck_beatmap_leaderboard_user_bests_mod_filter_key_non_negative",
        "beatmap_leaderboard_user_bests",
        "mod_filter_key IS NULL OR mod_filter_key >= 0",
    )
    op.create_index(
        "idx_beatmap_leaderboard_user_bests_scope_unique",
        "beatmap_leaderboard_user_bests",
        [
            "beatmap_id",
            "ruleset",
            "playstyle",
            "user_id",
            sa.text("COALESCE(mod_filter_key, -1)"),
        ],
        unique=True,
    )
    op.create_index(
        "idx_beatmap_leaderboard_user_bests_ordering",
        "beatmap_leaderboard_user_bests",
        [
            "beatmap_id",
            "ruleset",
            "playstyle",
            sa.text("COALESCE(mod_filter_key, -1)"),
            sa.text("score DESC"),
            sa.text("submitted_at ASC"),
            sa.text("score_id ASC"),
        ],
    )


def _upgrade_score_enums() -> None:
    op.drop_constraint("ck_scores_play_time_source_known", "scores", type_="check")
    op.alter_column(
        "scores",
        "grade",
        existing_type=sa.String(length=2),
        type_=SCORE_GRADE_ENUM,
        existing_nullable=False,
        postgresql_using="grade::text::score_grade",
    )
    op.alter_column(
        "scores",
        "beatmap_status_at_submission",
        existing_type=sa.String(length=32),
        type_=BEATMAP_RANK_STATUS_ENUM,
        existing_nullable=True,
        postgresql_using="beatmap_status_at_submission::text::beatmap_rank_status",
    )
    op.alter_column(
        "scores",
        "play_time_source",
        existing_type=sa.String(length=32),
        type_=PLAY_TIME_SOURCE_ENUM,
        existing_nullable=True,
        postgresql_using="play_time_source::text::play_time_source",
    )
    op.alter_column(
        "score_submissions",
        "state",
        existing_type=sa.String(length=32),
        type_=SCORE_SUBMISSION_STATE_ENUM,
        existing_nullable=False,
        postgresql_using="state::text::score_submission_state",
    )


def _downgrade_score_enums() -> None:
    op.alter_column(
        "score_submissions",
        "state",
        existing_type=SCORE_SUBMISSION_STATE_ENUM,
        type_=sa.String(length=32),
        existing_nullable=False,
        postgresql_using="state::text",
    )
    op.alter_column(
        "scores",
        "play_time_source",
        existing_type=PLAY_TIME_SOURCE_ENUM,
        type_=sa.String(length=32),
        existing_nullable=True,
        postgresql_using="play_time_source::text",
    )
    op.alter_column(
        "scores",
        "beatmap_status_at_submission",
        existing_type=BEATMAP_RANK_STATUS_ENUM,
        type_=sa.String(length=32),
        existing_nullable=True,
        postgresql_using="beatmap_status_at_submission::text",
    )
    op.alter_column(
        "scores",
        "grade",
        existing_type=SCORE_GRADE_ENUM,
        type_=sa.String(length=2),
        existing_nullable=False,
        postgresql_using="grade::text",
    )
    op.create_check_constraint(
        "ck_scores_play_time_source_known",
        "scores",
        "play_time_source IS NULL OR play_time_source IN ('fail_time', 'beatmap_total_length')",
    )


def _upgrade_beatmap_enums() -> None:
    op.execute(
        sa.text(
            """
            UPDATE beatmaps
            SET mode = 'unknown'
            WHERE mode NOT IN ('osu', 'taiko', 'fruits', 'mania')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE beatmap_fetch_states
            SET target_type = CASE target_type
                WHEN 'beatmap' THEN 'metadata:beatmap'
                WHEN 'beatmapset' THEN 'metadata:beatmapset'
                WHEN 'checksum' THEN 'metadata:checksum'
                WHEN 'file' THEN 'file:beatmap'
                ELSE target_type
            END
            """
        )
    )
    _alter_enum_column(
        "beatmapsets",
        "official_status",
        sa.String(length=32),
        BEATMAP_RANK_STATUS_ENUM,
        "beatmap_rank_status",
    )
    _alter_enum_column(
        "beatmapsets",
        "official_status_source",
        sa.String(length=64),
        BEATMAP_METADATA_SOURCE_ENUM,
        "beatmap_metadata_source",
    )
    _alter_enum_column(
        "beatmaps",
        "mode",
        sa.String(length=16),
        BEATMAP_MODE_ENUM,
        "beatmap_mode",
    )
    _alter_enum_column(
        "beatmaps",
        "official_status",
        sa.String(length=32),
        BEATMAP_RANK_STATUS_ENUM,
        "beatmap_rank_status",
    )
    _alter_enum_column(
        "beatmaps",
        "official_status_source",
        sa.String(length=64),
        BEATMAP_METADATA_SOURCE_ENUM,
        "beatmap_metadata_source",
    )
    _alter_enum_column(
        "beatmaps",
        "local_status_override",
        sa.String(length=32),
        LOCAL_BEATMAP_STATUS_ENUM,
        "local_beatmap_status",
        nullable=True,
    )
    _alter_enum_column(
        "beatmap_file_attachments",
        "source",
        sa.String(length=32),
        BEATMAP_FILE_SOURCE_ENUM,
        "beatmap_file_source",
    )
    _alter_enum_column(
        "beatmap_fetch_states",
        "target_type",
        sa.String(length=32),
        BEATMAP_FETCH_TARGET_KIND_ENUM,
        "beatmap_fetch_target_kind",
    )
    _alter_enum_column(
        "beatmap_fetch_states",
        "status",
        sa.String(length=32),
        BEATMAP_FETCH_STATE_ENUM,
        "beatmap_fetch_state",
    )


def _downgrade_beatmap_enums() -> None:
    _alter_string_column(
        "beatmap_fetch_states",
        "status",
        BEATMAP_FETCH_STATE_ENUM,
        length=32,
    )
    _alter_string_column(
        "beatmap_fetch_states",
        "target_type",
        BEATMAP_FETCH_TARGET_KIND_ENUM,
        length=32,
    )
    op.execute(
        sa.text(
            """
            UPDATE beatmap_fetch_states
            SET target_type = CASE target_type
                WHEN 'metadata:beatmap' THEN 'beatmap'
                WHEN 'metadata:beatmapset' THEN 'beatmapset'
                WHEN 'metadata:checksum' THEN 'checksum'
                WHEN 'file:beatmap' THEN 'file'
                ELSE target_type
            END
            """
        )
    )
    _alter_string_column(
        "beatmap_file_attachments",
        "source",
        BEATMAP_FILE_SOURCE_ENUM,
        length=32,
    )
    _alter_string_column(
        "beatmaps",
        "local_status_override",
        LOCAL_BEATMAP_STATUS_ENUM,
        length=32,
        nullable=True,
    )
    _alter_string_column(
        "beatmaps",
        "mode",
        BEATMAP_MODE_ENUM,
        length=16,
    )
    _alter_string_column(
        "beatmaps",
        "official_status_source",
        BEATMAP_METADATA_SOURCE_ENUM,
        length=64,
    )
    _alter_string_column(
        "beatmaps",
        "official_status",
        BEATMAP_RANK_STATUS_ENUM,
        length=32,
    )
    _alter_string_column(
        "beatmapsets",
        "official_status_source",
        BEATMAP_METADATA_SOURCE_ENUM,
        length=64,
    )
    _alter_string_column(
        "beatmapsets",
        "official_status",
        BEATMAP_RANK_STATUS_ENUM,
        length=32,
    )


def _upgrade_blob_enums() -> None:
    _alter_enum_column(
        "blobs",
        "storage_backend",
        sa.String(length=32),
        BLOB_STORAGE_BACKEND_ENUM,
        "blob_storage_backend",
    )


def _downgrade_blob_enums() -> None:
    _alter_string_column(
        "blobs",
        "storage_backend",
        BLOB_STORAGE_BACKEND_ENUM,
        length=32,
    )


def _upgrade_channel_enums() -> None:
    op.alter_column(
        "channels",
        "channel_type",
        existing_type=sa.String(length=16),
        server_default=None,
        existing_nullable=False,
    )
    op.alter_column(
        "channels",
        "channel_type",
        existing_type=sa.String(length=16),
        type_=CHANNEL_TYPE_ENUM,
        existing_nullable=False,
        postgresql_using="channel_type::text::channel_type",
    )
    op.alter_column(
        "channels",
        "channel_type",
        existing_type=CHANNEL_TYPE_ENUM,
        server_default=sa.text("'public'::channel_type"),
        existing_nullable=False,
    )


def _downgrade_channel_enums() -> None:
    op.alter_column(
        "channels",
        "channel_type",
        existing_type=CHANNEL_TYPE_ENUM,
        server_default=None,
        existing_nullable=False,
    )
    op.alter_column(
        "channels",
        "channel_type",
        existing_type=CHANNEL_TYPE_ENUM,
        type_=sa.String(length=16),
        existing_nullable=False,
        postgresql_using="channel_type::text",
    )
    op.alter_column(
        "channels",
        "channel_type",
        existing_type=sa.String(length=16),
        server_default="public",
        existing_nullable=False,
    )


def _upgrade_personal_best_enums() -> None:
    _alter_enum_column(
        "personal_bests",
        "category",
        sa.String(length=32),
        LEADERBOARD_CATEGORY_ENUM,
        "leaderboard_category",
    )


def _downgrade_personal_best_enums() -> None:
    _alter_string_column(
        "personal_bests",
        "category",
        LEADERBOARD_CATEGORY_ENUM,
        length=32,
    )


def _upgrade_performance_enums() -> None:
    op.drop_constraint(
        "ck_score_performance_unavailable_reason",
        "score_performance_calculations",
        type_="check",
    )
    op.drop_constraint(
        "ck_score_performance_completed_values",
        "score_performance_calculations",
        type_="check",
    )
    op.drop_constraint(
        "ck_score_performance_state_known",
        "score_performance_calculations",
        type_="check",
    )
    _alter_enum_column(
        "score_performance_calculations",
        "state",
        sa.String(length=32),
        PERFORMANCE_CALCULATION_STATE_ENUM,
        "performance_calculation_state",
    )
    _alter_enum_column(
        "score_performance_calculations",
        "formula_profile",
        sa.String(length=64),
        FORMULA_PROFILE_ENUM,
        "formula_profile",
    )
    op.create_check_constraint(
        "ck_score_performance_completed_values",
        "score_performance_calculations",
        "state::text != 'completed' OR "
        "(pp IS NOT NULL AND star_rating IS NOT NULL AND calculated_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_score_performance_unavailable_reason",
        "score_performance_calculations",
        "state::text != 'unavailable' OR unavailable_reason IS NOT NULL",
    )
    _alter_enum_column(
        "performance_recalculation_batches",
        "status",
        sa.String(length=32),
        PERFORMANCE_RECALCULATION_BATCH_STATUS_ENUM,
        "performance_recalculation_batch_status",
    )
    _alter_enum_column(
        "performance_recalculation_batches",
        "target_formula_profile",
        sa.String(length=64),
        FORMULA_PROFILE_ENUM,
        "formula_profile",
    )
    _alter_enum_column(
        "performance_recalculation_work_items",
        "reason",
        sa.String(length=64),
        PERFORMANCE_RECALCULATION_REASON_ENUM,
        "performance_recalculation_reason",
    )
    _alter_enum_column(
        "performance_recalculation_work_items",
        "state",
        sa.String(length=32),
        PERFORMANCE_RECALCULATION_WORK_ITEM_STATE_ENUM,
        "performance_recalculation_work_item_state",
    )


def _downgrade_performance_enums() -> None:
    _alter_string_column(
        "performance_recalculation_work_items",
        "state",
        PERFORMANCE_RECALCULATION_WORK_ITEM_STATE_ENUM,
        length=32,
    )
    _alter_string_column(
        "performance_recalculation_work_items",
        "reason",
        PERFORMANCE_RECALCULATION_REASON_ENUM,
        length=64,
    )
    _alter_string_column(
        "performance_recalculation_batches",
        "target_formula_profile",
        FORMULA_PROFILE_ENUM,
        length=64,
    )
    _alter_string_column(
        "performance_recalculation_batches",
        "status",
        PERFORMANCE_RECALCULATION_BATCH_STATUS_ENUM,
        length=32,
    )
    op.drop_constraint(
        "ck_score_performance_unavailable_reason",
        "score_performance_calculations",
        type_="check",
    )
    op.drop_constraint(
        "ck_score_performance_completed_values",
        "score_performance_calculations",
        type_="check",
    )
    _alter_string_column(
        "score_performance_calculations",
        "formula_profile",
        FORMULA_PROFILE_ENUM,
        length=64,
    )
    _alter_string_column(
        "score_performance_calculations",
        "state",
        PERFORMANCE_CALCULATION_STATE_ENUM,
        length=32,
    )
    op.create_check_constraint(
        "ck_score_performance_state_known",
        "score_performance_calculations",
        "state IN ('queued', 'fetching_file', 'calculating', 'completed', "
        "'unavailable', 'superseded')",
    )
    op.create_check_constraint(
        "ck_score_performance_completed_values",
        "score_performance_calculations",
        "state != 'completed' OR "
        "(pp IS NOT NULL AND star_rating IS NOT NULL AND calculated_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_score_performance_unavailable_reason",
        "score_performance_calculations",
        "state != 'unavailable' OR unavailable_reason IS NOT NULL",
    )


def _alter_enum_column(
    table_name: str,
    column_name: str,
    existing_type: sa.TypeEngine[object],
    enum_type: postgresql.ENUM,
    enum_name: str,
    *,
    nullable: bool = False,
) -> None:
    op.alter_column(
        table_name,
        column_name,
        existing_type=existing_type,
        type_=enum_type,
        existing_nullable=nullable,
        postgresql_using=f"{column_name}::text::{enum_name}",
    )


def _alter_string_column(
    table_name: str,
    column_name: str,
    existing_type: postgresql.ENUM,
    *,
    length: int,
    nullable: bool = False,
) -> None:
    op.alter_column(
        table_name,
        column_name,
        existing_type=existing_type,
        type_=sa.String(length=length),
        existing_nullable=nullable,
        postgresql_using=f"{column_name}::text",
    )
