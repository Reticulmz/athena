"""Beatmap resolution結果とscore提出適格性を定義するmodule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps.entities import Beatmap, BeatmapSet
    from osu_server.domain.beatmaps.states import (
        BeatmapFetchState,
        BeatmapFileState,
        BeatmapMetadataSource,
    )


@dataclass(slots=True, frozen=True)
class BeatmapEligibility:
    """Score submissionとleaderboard更新で使うbeatmap適格性を表す.

    Attributes:
        accepts_scores (bool): score submissionを受け付けるか.
        has_leaderboard (bool): leaderboardを持つか.
        awards_ranked_pp (bool): ranked PPを付与するか.
        awards_loved_pp (bool): loved PPを付与するか.
        requires_osu_file_for_pp (bool): PP計算にosu fileを必要とするか.
        is_officially_verified (bool): metadataが公式情報として検証済みか.
        is_mirror_derived (bool): metadataがmirror由来か.
        accepts_failed_scores (bool): failed scoreを受け付けるか.
        failed_scores_have_leaderboard (bool): failed scoreをleaderboardへ反映するか.
        failed_scores_update_best_score (bool): failed scoreでbest scoreを更新するか.
        failed_scores_award_ranked_pp (bool): failed scoreにranked PPを付与するか.
        failed_scores_award_loved_pp (bool): failed scoreにloved PPを付与するか.
        denial_reason (str | None): scoreを受け付けない理由. 受け付ける場合はNone.
    """

    accepts_scores: bool
    has_leaderboard: bool
    awards_ranked_pp: bool
    awards_loved_pp: bool
    requires_osu_file_for_pp: bool
    is_officially_verified: bool
    is_mirror_derived: bool
    accepts_failed_scores: bool
    failed_scores_have_leaderboard: bool
    failed_scores_update_best_score: bool
    failed_scores_award_ranked_pp: bool
    failed_scores_award_loved_pp: bool
    denial_reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapResolveOptions:
    """Beatmap resolutionの挙動を制御するoptionを表す.

    Attributes:
        require_osu_file (bool): resultにosu fileが存在することを必須にするか.
        wait_timeout_seconds (float): 進行中fetchの完了を待つ最大秒数.
        force_refresh (bool): cached metadataにかかわらずrefreshを要求するか.
    """

    require_osu_file: bool = False
    wait_timeout_seconds: float = 0.0
    force_refresh: bool = False


@dataclass(slots=True, frozen=True)
class BeatmapResolveResult:
    """単一beatmap resolutionの構造化された結果を表す.

    Attributes:
        beatmap (Beatmap | None): 解決したbeatmap. 解決不能時はNone.
        beatmapset (BeatmapSet | None): beatmapが属するset. 解決不能時はNone.
        eligibility (BeatmapEligibility | None): 解決したbeatmapの適格性. 解決不能時はNone.
        metadata_status (BeatmapFetchState): metadata fetchの状態.
        file_status (BeatmapFileState): osu file fetchの状態.
        source (BeatmapMetadataSource | None): 利用したmetadata source. 未確定時はNone.
        verified (bool): metadataが公式情報として検証済みか.
        last_fetched_at (datetime | None): metadataを最後に取得した日時. 未取得時はNone.
        next_refresh_at (datetime | None): 次回metadata refresh予定日時. 未設定時はNone.
        reason (str | None): 解決不能または保留の理由. 解決時はNone.
    """

    beatmap: Beatmap | None
    beatmapset: BeatmapSet | None
    eligibility: BeatmapEligibility | None
    metadata_status: BeatmapFetchState
    file_status: BeatmapFileState
    source: BeatmapMetadataSource | None
    verified: bool
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None
    reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapSetResolveResult:
    """Beatmapset resolutionの構造化された結果を表す.

    Attributes:
        beatmapset (BeatmapSet | None): 解決したbeatmapset. 解決不能時はNone.
        metadata_status (BeatmapFetchState): metadata fetchの状態.
        source (BeatmapMetadataSource | None): 利用したmetadata source. 未確定時はNone.
        verified (bool): metadataが公式情報として検証済みか.
        last_fetched_at (datetime | None): metadataを最後に取得した日時. 未取得時はNone.
        next_refresh_at (datetime | None): 次回metadata refresh予定日時. 未設定時はNone.
        reason (str | None): 解決不能または保留の理由. 解決時はNone.
    """

    beatmapset: BeatmapSet | None
    metadata_status: BeatmapFetchState
    source: BeatmapMetadataSource | None
    verified: bool
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None
    reason: str | None
