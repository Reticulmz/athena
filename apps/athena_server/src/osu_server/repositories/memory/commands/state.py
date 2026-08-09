"""In-memory command repository が共有する可変 state を定義する module."""

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
        BeatmapSetSearchDocument,
        DirectCoverageRecord,
        DirectExternalIndexBackend,
        DirectExternalIndexState,
    )
    from osu_server.domain.chat.channels import Channel, ChannelRoleOverride
    from osu_server.domain.identity.roles import Role
    from osu_server.domain.identity.users import User
    from osu_server.domain.scores.performance import FormulaProfile, PerformanceCalculation
    from osu_server.domain.scores.personal_best import PersonalBest
    from osu_server.domain.scores.replay import Replay
    from osu_server.domain.scores.score import Score
    from osu_server.domain.scores.submission import ScoreSubmission
    from osu_server.domain.scores.user_stats import UserStatsProjection
    from osu_server.domain.storage.blobs import Blob
    from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
        BeatmapLeaderboardUserBest,
    )
    from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
        BeatmapPerformanceBest,
    )
    from osu_server.repositories.interfaces.commands.beatmaps import BeatmapSubmissionCounts


@dataclass(slots=True, frozen=True)
class InMemoryChannelMessageRecord:
    """In-memory repository に保存済みの channel message 履歴行を表す.

    Attributes:
        id (int): message の repository 内一意識別子.
        sender_id (int): message を送信した user の識別子.
        channel_id (int): 宛先 channel の識別子.
        channel_name (str): 保存時点の channel 名.
        content (str): 保存した message 本文.
        created_at (datetime): 保存時に採番した UTC timestamp.
    """

    id: int
    sender_id: int
    channel_id: int
    channel_name: str
    content: str
    created_at: datetime


@dataclass(slots=True, frozen=True)
class InMemoryPrivateMessageRecord:
    """In-memory repository に保存済みの private message 履歴行を表す.

    Attributes:
        id (int): message の repository 内一意識別子.
        sender_id (int): message を送信した user の識別子.
        target_id (int): message の宛先 user の識別子.
        content (str): 保存した message 本文.
        created_at (datetime): 保存時に採番した UTC timestamp.
    """

    id: int
    sender_id: int
    target_id: int
    content: str
    created_at: datetime


@dataclass(slots=True, frozen=True)
class InMemoryFriendRelationshipRecord:
    """In-memory repository に保存済みの有向 friend relationship 行を表す.

    Attributes:
        owner_user_id (int): relationship を所有する user の識別子.
        target_user_id (int): relationship の対象 user の識別子.
        created_at (datetime): relationship を作成した UTC timestamp.
    """

    owner_user_id: int
    target_user_id: int
    created_at: datetime


@dataclass(slots=True, frozen=True)
class InMemoryPerformanceClaim:
    """Performance row 又は work item に対する worker claim の metadata を表す.

    Attributes:
        owner (str): claim を取得した worker の識別子.
        expires_at (datetime): claim が無効になる UTC timestamp.
        attempt_count (int): 対象に対して行われた claim の試行回数.
    """

    owner: str
    expires_at: datetime
    attempt_count: int


@dataclass(slots=True, frozen=True)
class InMemoryPerformanceRecalculationBatchRecord:
    """In-memory repository に保存済みの performance recalculation batch 行を表す.

    Attributes:
        id (int): batch の repository 内一意識別子.
        status (str): persistence Enum value として保持する batch state.
        filters (dict[str, object]): batch 作成時の対象絞り込み条件.
        reason_counts (dict[str, int]): reason value ごとの候補数.
        target_calculator_version (str): 再計算対象 calculator version.
        target_formula_profile (FormulaProfile): 再計算対象 formula profile.
        candidate_count (int): batch に作成した work item 数.
        completed_count (int): 完了した work item 数.
        unavailable_count (int): unavailable で終了した work item 数.
        created_at (datetime): batch 作成時の UTC timestamp.
        updated_at (datetime): batch の最終更新 UTC timestamp.
    """

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
    """In-memory repository に保存済みの performance recalculation work item を表す.

    Attributes:
        id (int): work item の repository 内一意識別子.
        batch_id (int): 所属する recalculation batch の識別子.
        score_id (int): 再計算対象 score の識別子.
        reason (str): persistence Enum value として保持する再計算理由.
        state (str): persistence Enum value として保持する work item state.
        calculation_id (int | None): 完了時に関連付けた calculation の識別子.
        claim (InMemoryPerformanceClaim | None): 現在有効又は期限切れの claim metadata.
        attempt_count (int): claim を取得した試行回数.
        last_error (str | None): 最後に記録した unavailable 又は failure 理由.
        created_at (datetime): work item 作成時の UTC timestamp.
        updated_at (datetime): work item の最終更新 UTC timestamp.
    """

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
    """一つの in-memory command transaction が使用する可変 state snapshot を保持する.

    Attributes:
        users_by_id (dict[int, User]): user ID をキーにした user の主記録.
        user_id_by_safe_username (dict[str, int]): 小文字化 safe username の一意 index.
        user_id_by_email (dict[str, int]): 小文字化 email の一意 index.
        disallowed_usernames (set[str]): 小文字化した利用禁止 username.
        next_user_id (int): 次に user へ割り当てる識別子.
        roles_by_id (dict[int, Role]): role ID をキーにした role の主記録.
        role_id_by_name (dict[str, int]): role name の一意 index.
        role_ids_by_user_id (dict[int, set[int]]): user ごとの割当 role ID 集合.
        channels_by_id (dict[int, Channel]): channel ID をキーにした channel の主記録.
        channel_id_by_name (dict[str, int]): channel name の一意 index.
        channel_overrides_by_channel_id (dict[int, list[ChannelRoleOverride]]):
            channel ACL override.
        next_channel_id (int): 次に channel へ割り当てる識別子.
        channel_messages_by_id (dict[int, InMemoryChannelMessageRecord]): channel message 履歴.
        private_messages_by_id (dict[int, InMemoryPrivateMessageRecord]): private message 履歴.
        next_channel_message_id (int): 次に channel message へ割り当てる識別子.
        next_private_message_id (int): 次に private message へ割り当てる識別子.
        friend_relationships_by_key (dict[tuple[int, int],
            InMemoryFriendRelationshipRecord]):
            有向 friendship の一意 index.
        scores_by_id (dict[int, Score]): score ID をキーにした score の主記録.
        score_id_by_online_checksum (dict[str, int]): online checksum の一意 index.
        score_leaderboard_eligibility_by_id (dict[int, bool]):
            submission 時点の leaderboard eligibility.
        next_score_id (int): 次に score へ割り当てる識別子.
        personal_bests_by_id (dict[int, PersonalBest]): personal best の主記録.
        personal_best_id_by_scope (dict[tuple[int, int, int, int, str], int]):
            personal best scope の一意 index.
        next_personal_best_id (int): 次に personal best へ割り当てる識別子.
        beatmap_leaderboard_user_bests_by_id (dict[int, BeatmapLeaderboardUserBest]):
            leaderboard best の主記録.
        beatmap_leaderboard_user_best_id_by_scope (dict[tuple[int, int, int, int, int],
            int]): leaderboard best scope の一意 index.
        next_beatmap_leaderboard_user_best_id (int): 次に leaderboard best へ割り当てる識別子.
        beatmap_performance_bests_by_id (dict[int, BeatmapPerformanceBest]):
            performance best の主記録.
        beatmap_performance_best_id_by_scope (dict[tuple[int, int, int, int], int]):
            performance best scope の一意 index.
        next_beatmap_performance_best_id (int): 次に performance best へ割り当てる識別子.
        current_user_stats_by_scope (dict[tuple[int, int, int], UserStatsProjection]):
            current user stats projection.
        submissions_by_id (dict[int, ScoreSubmission]): score submission の主記録.
        submission_id_by_fingerprint (dict[str, int]): submission fingerprint の一意 index.
        next_submission_id (int): 次に submission へ割り当てる識別子.
        replays_by_id (dict[int, Replay]): replay の主記録.
        replay_id_by_checksum (dict[str, int]): replay checksum の一意 index.
        next_replay_id (int): 次に replay へ割り当てる識別子.
        blobs_by_id (dict[int, Blob]): blob metadata の主記録.
        blob_id_by_sha256 (dict[str, int]): SHA-256 の一意 index.
        next_blob_id (int): 次に blob へ割り当てる識別子.
        beatmapsets_by_id (dict[int, BeatmapSet]): beatmapset の主記録.
        beatmaps_by_id (dict[int, Beatmap]): beatmap の主記録.
        beatmap_id_by_checksum (dict[str, int]): beatmap MD5 checksum の一意 index.
        beatmap_submission_counts_by_id (dict[int, BeatmapSubmissionCounts]):
            beatmap ごとの集計 submission count.
        search_documents_by_beatmapset_id (dict[int, BeatmapSetSearchDocument]):
            osu!direct検索projectionの主記録.
        direct_coverage_records_by_scope (dict[tuple[str, str, str, str, str, int, int],
            DirectCoverageRecord]): feed windowまたはid range crawlのcoverage state.
        external_index_states_by_key (dict[tuple[DirectExternalIndexBackend, int],
            DirectExternalIndexState]): external index backendとbeatmapset IDごとの同期状態.
        attachments_by_key (dict[tuple[int, str], BeatmapFileAttachment]):
            beatmap file attachment の主記録.
        attachment_keys_by_beatmap_id (dict[int, list[tuple[int, str]]]):
            beatmap ごとの attachment 挿入順 index.
        fetch_states_by_target (dict[BeatmapFetchTarget, BeatmapFetchRecord]):
            beatmap fetch target ごとの状態.
        performance_calculations_by_id (dict[int, PerformanceCalculation]):
            performance calculation の主記録.
        current_performance_calculation_id_by_score_id (dict[int, int]):
            score ごとの current calculation index.
        replacement_performance_calculation_id_by_score_id (dict[int, int]):
            score ごとの replacement calculation index.
        performance_claims_by_calculation_id (dict[int, InMemoryPerformanceClaim]):
            pending calculation の worker claim.
        next_performance_calculation_id (int): 次に performance calculation へ割り当てる識別子.
        performance_recalculation_batches_by_id (dict[int,
            InMemoryPerformanceRecalculationBatchRecord]): recalculation batch の主記録.
        performance_recalculation_work_items_by_id (dict[int,
            InMemoryPerformanceRecalculationWorkItemRecord]):
            recalculation work item の主記録.
        performance_recalculation_work_item_ids_by_batch_id (dict[int, list[int]]):
            batch ごとの work item 挿入順 index.
        next_performance_recalculation_batch_id (int): 次に recalculation batch へ割り当てる識別子.
        next_performance_recalculation_work_item_id (int):
            次に recalculation work item へ割り当てる識別子.

    Notes:
        この class 自体は同期化を行わない. 同じ instance を複数 task 又は thread から
        同時に変更してはならない. command Unit of Work は transaction ごとに clone を使用する.
    """

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
        tuple[int, int, int, int, int],
        int,
    ] = field(default_factory=dict)
    next_beatmap_leaderboard_user_best_id: int = 1

    beatmap_performance_bests_by_id: dict[int, BeatmapPerformanceBest] = field(
        default_factory=dict
    )
    beatmap_performance_best_id_by_scope: dict[
        tuple[int, int, int, int],
        int,
    ] = field(default_factory=dict)
    next_beatmap_performance_best_id: int = 1

    current_user_stats_by_scope: dict[tuple[int, int, int], UserStatsProjection] = field(
        default_factory=dict
    )

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
    beatmap_submission_counts_by_id: dict[int, BeatmapSubmissionCounts] = field(
        default_factory=dict
    )
    search_documents_by_beatmapset_id: dict[int, BeatmapSetSearchDocument] = field(
        default_factory=dict
    )
    direct_coverage_records_by_scope: dict[
        tuple[str, str, str, str, str, int, int],
        DirectCoverageRecord,
    ] = field(default_factory=dict)
    external_index_states_by_key: dict[
        tuple[DirectExternalIndexBackend, int],
        DirectExternalIndexState,
    ] = field(default_factory=dict)
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
        """Command transaction 用に state 全体の独立した deep copy を返す.

        Returns:
            Self: すべての主記録と index を複製した独立 snapshot.

        Notes:
            複製後の mutable container は元の state と共有しない. この method 自体は
            同期化を行わないため, 呼び出し側は state の所有権を直列化する必要がある.
        """
        return deepcopy(self)


def now_utc() -> datetime:
    """In-memory command repository が使用する現在 UTC timestamp を返す.

    Returns:
        datetime: UTC timezone を持つ現在時刻.
    """
    return datetime.now(UTC)
