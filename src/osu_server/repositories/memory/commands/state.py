"""Shared in-memory command repository state."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapFileAttachment,
        BeatmapSet,
    )
    from osu_server.domain.chat.channels import Channel, ChannelRoleOverride
    from osu_server.domain.identity.roles import Role
    from osu_server.domain.identity.users import User
    from osu_server.domain.scores.performance import FormulaProfile, PerformanceCalculation
    from osu_server.domain.scores.personal_best import PersonalBest
    from osu_server.domain.scores.replay import Replay
    from osu_server.domain.scores.score import Score
    from osu_server.domain.scores.submission import ScoreSubmission
    from osu_server.domain.storage.blobs import Blob
    from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
        BeatmapLeaderboardUserBest,
    )


@dataclass(slots=True, frozen=True)
class InMemoryChannelMessageRecord:
    """Committed channel chat history row for memory repositories."""

    id: int
    sender_id: int
    channel_id: int
    channel_name: str
    content: str
    created_at: datetime


@dataclass(slots=True, frozen=True)
class InMemoryPrivateMessageRecord:
    """Committed private chat history row for memory repositories."""

    id: int
    sender_id: int
    target_id: int
    content: str
    created_at: datetime


@dataclass(slots=True, frozen=True)
class InMemoryFriendRelationshipRecord:
    """Committed directed friend relationship row for memory repositories."""

    owner_user_id: int
    target_user_id: int
    created_at: datetime


@dataclass(slots=True, frozen=True)
class InMemoryPerformanceClaim:
    """In-memory worker claim metadata for performance rows and work items."""

    owner: str
    expires_at: datetime
    attempt_count: int


@dataclass(slots=True, frozen=True)
class InMemoryPerformanceRecalculationBatchRecord:
    """Committed performance recalculation batch row for memory repositories."""

    id: int
    status: str
    filters: dict[str, object]
    reason_counts: dict[str, int]
    target_calculator_version: str
    target_formula_profile: FormulaProfile
    candidate_count: int
    completed_count: int
    unavailable_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class InMemoryPerformanceRecalculationWorkItemRecord:
    """Committed performance recalculation work item row for memory repositories."""

    id: int
    batch_id: int
    score_id: int
    reason: str
    state: str
    calculation_id: int | None
    claim: InMemoryPerformanceClaim | None
    attempt_count: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class InMemoryCommandRepositoryState:
    """Mutable state snapshot used by one in-memory command transaction."""

    users_by_id: dict[int, User] = field(default_factory=dict)
    user_id_by_safe_username: dict[str, int] = field(default_factory=dict)
    user_id_by_email: dict[str, int] = field(default_factory=dict)
    disallowed_usernames: set[str] = field(default_factory=set)
    next_user_id: int = 1

    roles_by_id: dict[int, Role] = field(default_factory=dict)
    role_id_by_name: dict[str, int] = field(default_factory=dict)
    role_ids_by_user_id: dict[int, set[int]] = field(default_factory=dict)

    channels_by_id: dict[int, Channel] = field(default_factory=dict)
    channel_id_by_name: dict[str, int] = field(default_factory=dict)
    channel_overrides_by_channel_id: dict[int, list[ChannelRoleOverride]] = field(
        default_factory=dict
    )
    next_channel_id: int = 1
    channel_messages_by_id: dict[int, InMemoryChannelMessageRecord] = field(default_factory=dict)
    private_messages_by_id: dict[int, InMemoryPrivateMessageRecord] = field(default_factory=dict)
    next_channel_message_id: int = 1
    next_private_message_id: int = 1

    friend_relationships_by_key: dict[
        tuple[int, int],
        InMemoryFriendRelationshipRecord,
    ] = field(default_factory=dict)

    scores_by_id: dict[int, Score] = field(default_factory=dict)
    score_id_by_online_checksum: dict[str, int] = field(default_factory=dict)
    score_leaderboard_eligibility_by_id: dict[int, bool] = field(default_factory=dict)
    next_score_id: int = 1

    personal_bests_by_id: dict[int, PersonalBest] = field(default_factory=dict)
    personal_best_id_by_scope: dict[tuple[int, int, int, int, str], int] = field(
        default_factory=dict
    )
    next_personal_best_id: int = 1

    beatmap_leaderboard_user_bests_by_id: dict[int, BeatmapLeaderboardUserBest] = field(
        default_factory=dict
    )
    beatmap_leaderboard_user_best_id_by_scope: dict[
        tuple[int, int, int, int, int | None],
        int,
    ] = field(default_factory=dict)
    next_beatmap_leaderboard_user_best_id: int = 1

    submissions_by_id: dict[int, ScoreSubmission] = field(default_factory=dict)
    submission_id_by_fingerprint: dict[str, int] = field(default_factory=dict)
    next_submission_id: int = 1

    replays_by_id: dict[int, Replay] = field(default_factory=dict)
    replay_id_by_checksum: dict[str, int] = field(default_factory=dict)
    next_replay_id: int = 1

    blobs_by_id: dict[int, Blob] = field(default_factory=dict)
    blob_id_by_sha256: dict[str, int] = field(default_factory=dict)
    next_blob_id: int = 1

    beatmapsets_by_id: dict[int, BeatmapSet] = field(default_factory=dict)
    beatmaps_by_id: dict[int, Beatmap] = field(default_factory=dict)
    beatmap_id_by_checksum: dict[str, int] = field(default_factory=dict)
    attachments_by_key: dict[tuple[int, str], BeatmapFileAttachment] = field(default_factory=dict)
    attachment_keys_by_beatmap_id: dict[int, list[tuple[int, str]]] = field(default_factory=dict)
    fetch_states_by_target: dict[BeatmapFetchTarget, BeatmapFetchRecord] = field(
        default_factory=dict
    )

    performance_calculations_by_id: dict[int, PerformanceCalculation] = field(default_factory=dict)
    current_performance_calculation_id_by_score_id: dict[int, int] = field(default_factory=dict)
    replacement_performance_calculation_id_by_score_id: dict[int, int] = field(
        default_factory=dict
    )
    performance_claims_by_calculation_id: dict[int, InMemoryPerformanceClaim] = field(
        default_factory=dict
    )
    next_performance_calculation_id: int = 1

    performance_recalculation_batches_by_id: dict[
        int, InMemoryPerformanceRecalculationBatchRecord
    ] = field(default_factory=dict)
    performance_recalculation_work_items_by_id: dict[
        int, InMemoryPerformanceRecalculationWorkItemRecord
    ] = field(default_factory=dict)
    performance_recalculation_work_item_ids_by_batch_id: dict[int, list[int]] = field(
        default_factory=dict
    )
    next_performance_recalculation_batch_id: int = 1
    next_performance_recalculation_work_item_id: int = 1

    def clone(self) -> Self:
        """Return an isolated copy for a command transaction."""
        return deepcopy(self)


def now_utc() -> datetime:
    """Return the timestamp used by memory command repositories."""
    return datetime.now(UTC)
