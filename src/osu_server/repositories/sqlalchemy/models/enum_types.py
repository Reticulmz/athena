"""SQLAlchemy ORM model で共有する PostgreSQL enum type を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy.dialects.postgresql import ENUM

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
from osu_server.infrastructure.database.base import Base

if TYPE_CHECKING:
    from enum import Enum


def _enum_values(enum_type: type[Enum]) -> tuple[str, ...]:
    return tuple(cast("str", member.value) for member in enum_type)


def _postgres_enum(enum_type: type[Enum], *, name: str) -> ENUM:
    return ENUM(
        *_enum_values(enum_type),
        name=name,
        metadata=Base.metadata,
        validate_strings=True,
    )


BEATMAP_FETCH_STATE_ENUM = _postgres_enum(BeatmapFetchState, name="beatmap_fetch_state")
BEATMAP_FETCH_TARGET_KIND_ENUM = _postgres_enum(
    BeatmapFetchTargetKind,
    name="beatmap_fetch_target_kind",
)
BEATMAP_FILE_SOURCE_ENUM = _postgres_enum(BeatmapFileSource, name="beatmap_file_source")
BEATMAP_METADATA_SOURCE_ENUM = _postgres_enum(
    BeatmapMetadataSource,
    name="beatmap_metadata_source",
)
BEATMAP_MODE_ENUM = _postgres_enum(BeatmapMode, name="beatmap_mode")
BEATMAP_RANK_STATUS_ENUM = _postgres_enum(BeatmapRankStatus, name="beatmap_rank_status")
BLOB_STORAGE_BACKEND_ENUM = _postgres_enum(
    BlobStorageBackendKind,
    name="blob_storage_backend",
)
CHANNEL_TYPE_ENUM = _postgres_enum(ChannelType, name="channel_type")
FORMULA_PROFILE_ENUM = _postgres_enum(FormulaProfile, name="formula_profile")
LEADERBOARD_CATEGORY_ENUM = _postgres_enum(LeaderboardCategory, name="leaderboard_category")
LOCAL_BEATMAP_STATUS_ENUM = _postgres_enum(
    LocalBeatmapStatus,
    name="local_beatmap_status",
)
PERFORMANCE_CALCULATION_STATE_ENUM = _postgres_enum(
    PerformanceCalculationState,
    name="performance_calculation_state",
)
PERFORMANCE_RECALCULATION_BATCH_STATUS_ENUM = _postgres_enum(
    PerformanceRecalculationBatchStatus,
    name="performance_recalculation_batch_status",
)
PERFORMANCE_RECALCULATION_REASON_ENUM = _postgres_enum(
    RecalculationCandidateReason,
    name="performance_recalculation_reason",
)
PERFORMANCE_RECALCULATION_WORK_ITEM_STATE_ENUM = _postgres_enum(
    PerformanceRecalculationWorkItemState,
    name="performance_recalculation_work_item_state",
)
PLAY_TIME_SOURCE_ENUM = _postgres_enum(PlayTimeSource, name="play_time_source")
SCORE_GRADE_ENUM = _postgres_enum(Grade, name="score_grade")
SCORE_SUBMISSION_STATE_ENUM = _postgres_enum(
    ScoreSubmissionState,
    name="score_submission_state",
)
