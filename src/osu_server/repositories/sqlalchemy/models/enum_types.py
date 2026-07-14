"""SQLAlchemy ORM modelで共有するCHECK付き文字列Enumを定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import Enum as SQLAlchemyEnum

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFetchTargetKind,
    BeatmapFileSource,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    LocalBeatmapStatus,
)
from osu_server.domain.chat.channels import ChannelType
from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculationState,
    PerformanceRecalculationBatchStatus,
    PerformanceRecalculationWorkItemState,
    RecalculationCandidateReason,
)
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.domain.scores.score import Grade, PlayTimeSource
from osu_server.domain.scores.submission import ScoreSubmissionState
from osu_server.domain.storage.blobs import BlobStorageBackendKind

if TYPE_CHECKING:
    from enum import Enum


def _enum_values(enum_type: type[Enum]) -> tuple[str, ...]:
    return tuple(cast("str", member.value) for member in enum_type)


def _checked_string_enum(
    enum_type: type[Enum],
    *,
    constraint_name: str,
    length: int,
) -> SQLAlchemyEnum:
    return SQLAlchemyEnum(
        *_enum_values(enum_type),
        name=constraint_name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=length,
    )


BEATMAP_FETCH_STATE_ENUM = _checked_string_enum(
    BeatmapFetchState,
    constraint_name="ck_beatmap_fetch_states_status_known",
    length=32,
)
BEATMAP_FETCH_TARGET_KIND_ENUM = _checked_string_enum(
    BeatmapFetchTargetKind,
    constraint_name="ck_beatmap_fetch_states_target_type_known",
    length=32,
)
BEATMAP_FILE_SOURCE_ENUM = _checked_string_enum(
    BeatmapFileSource,
    constraint_name="ck_beatmap_file_attachments_source_known",
    length=32,
)
BEATMAP_METADATA_SOURCE_ENUM = _checked_string_enum(
    BeatmapMetadataSource,
    constraint_name="ck_beatmap_metadata_source_known",
    length=64,
)
BEATMAP_MODE_ENUM = _checked_string_enum(
    BeatmapMode,
    constraint_name="ck_beatmaps_mode_known",
    length=16,
)
BEATMAP_RANK_STATUS_ENUM = _checked_string_enum(
    BeatmapRankStatus,
    constraint_name="ck_beatmap_rank_status_known",
    length=32,
)
BLOB_STORAGE_BACKEND_ENUM = _checked_string_enum(
    BlobStorageBackendKind,
    constraint_name="ck_blobs_storage_backend_known",
    length=32,
)
CHANNEL_TYPE_ENUM = _checked_string_enum(
    ChannelType,
    constraint_name="ck_channels_channel_type_known",
    length=16,
)
FORMULA_PROFILE_ENUM = _checked_string_enum(
    FormulaProfile,
    constraint_name="ck_formula_profile_known",
    length=64,
)
LEADERBOARD_CATEGORY_ENUM = _checked_string_enum(
    LeaderboardCategory,
    constraint_name="ck_personal_bests_category_known",
    length=32,
)
LOCAL_BEATMAP_STATUS_ENUM = _checked_string_enum(
    LocalBeatmapStatus,
    constraint_name="ck_beatmaps_local_status_override_known",
    length=32,
)
PERFORMANCE_CALCULATION_STATE_ENUM = _checked_string_enum(
    PerformanceCalculationState,
    constraint_name="ck_score_performance_state_known",
    length=32,
)
PERFORMANCE_RECALCULATION_BATCH_STATUS_ENUM = _checked_string_enum(
    PerformanceRecalculationBatchStatus,
    constraint_name="ck_performance_recalculation_batches_status_known",
    length=32,
)
PERFORMANCE_RECALCULATION_REASON_ENUM = _checked_string_enum(
    RecalculationCandidateReason,
    constraint_name="ck_performance_recalculation_work_items_reason_known",
    length=64,
)
PERFORMANCE_RECALCULATION_WORK_ITEM_STATE_ENUM = _checked_string_enum(
    PerformanceRecalculationWorkItemState,
    constraint_name="ck_performance_recalculation_work_items_state_known",
    length=32,
)
PLAY_TIME_SOURCE_ENUM = _checked_string_enum(
    PlayTimeSource,
    constraint_name="ck_scores_play_time_source_known",
    length=32,
)
SCORE_GRADE_ENUM = _checked_string_enum(
    Grade,
    constraint_name="ck_scores_grade_known",
    length=2,
)
SCORE_SUBMISSION_STATE_ENUM = _checked_string_enum(
    ScoreSubmissionState,
    constraint_name="ck_score_submissions_state_known",
    length=32,
)
