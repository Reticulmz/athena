"""Beatmap metadata freshness判定policyを定義するmodule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps.states import (
    BeatmapFetchState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
)

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from osu_server.domain.beatmaps.entities import Beatmap


_STABLE_STATUSES: frozenset[BeatmapRankStatus] = frozenset(
    {BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED, BeatmapRankStatus.LOVED}
)
_PENDING_LIKE_STATUSES: frozenset[BeatmapRankStatus] = frozenset(
    {BeatmapRankStatus.QUALIFIED, BeatmapRankStatus.PENDING, BeatmapRankStatus.WIP}
)


def _is_mirror_sourced(beatmap: Beatmap) -> bool:
    """Beatmap metadataがmirror由来かを返す.

    Args:
        beatmap (Beatmap): 取得元を確認するbeatmap.

    Returns:
        bool: official_status_sourceがMIRRORの場合はTrue.
    """
    return beatmap.official_status_source is BeatmapMetadataSource.MIRROR


@dataclass(slots=True, frozen=True)
class BeatmapFreshnessDecision:
    """Metadata freshness policyの判定結果を表す.

    Attributes:
        is_stale (bool): metadataがrefresh期限を過ぎたか,または公式sourceを利用できる
            mirror由来recordであるか.
        should_refresh (bool): metadata fetchを要求すべきか.
        requests_official_refresh (bool): mirror由来recordに公式sourceでの再取得を要求するか.
        next_refresh_at (datetime | None): 判定に使用した次回refresh日時. 未確定時はNone.
        reason (str | None): refresh判断の理由code. 通常のfresh状態ではNoneだが,
            PENDING_FETCHではpending_fetchを返す.
    """

    is_stale: bool
    should_refresh: bool
    requests_official_refresh: bool
    next_refresh_at: datetime | None
    reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapFreshnessPolicy:
    """Beatmap metadataを再取得すべきか判定するpolicyを表す.

    Attributes:
        ranked_refresh_interval (timedelta): ranked,approved,lovedのrefresh間隔.
        pending_refresh_interval (timedelta): qualified,pending,WIPなどのrefresh間隔.
        graveyard_refresh_interval (timedelta): graveyardのrefresh間隔.
        mirror_refresh_interval (timedelta): mirror由来metadataのrefresh間隔.
    """

    ranked_refresh_interval: timedelta
    pending_refresh_interval: timedelta
    graveyard_refresh_interval: timedelta
    mirror_refresh_interval: timedelta

    def evaluate(
        self,
        beatmap: Beatmap,
        *,
        now: datetime,
        official_sources_available: bool = False,
        force_refresh: bool = False,
    ) -> BeatmapFreshnessDecision:
        """現在時刻と取得元からstale/refresh判定を返す.

        Args:
            beatmap (Beatmap): freshnessを判定するbeatmap.
            now (datetime): 判定に使う現在時刻.
            official_sources_available (bool): 公式metadata sourceを利用できるか.
            force_refresh (bool): freshでもmetadata fetchを強制するか.

        Returns:
            BeatmapFreshnessDecision: stale状態,refresh要否,公式source再取得要否を含む判定結果.

        Notes:
            force_refreshがFalseのPENDING_FETCHではshould_refreshをFalseにし,
            reasonとしてpending_fetchを返す. 公式sourceが利用できるmirror由来recordは
            次回予定日時に関わらず公式再取得を要求する.
        """
        next_refresh_at = self._effective_next_refresh_at(beatmap)
        is_stale = beatmap.metadata_fetch_state is BeatmapFetchState.STALE or (
            next_refresh_at is not None and next_refresh_at <= now
        )

        if force_refresh:
            return BeatmapFreshnessDecision(
                is_stale=is_stale,
                should_refresh=True,
                requests_official_refresh=official_sources_available
                and _is_mirror_sourced(beatmap),
                next_refresh_at=next_refresh_at,
                reason="force_refresh",
            )

        if beatmap.metadata_fetch_state is BeatmapFetchState.PENDING_FETCH:
            return BeatmapFreshnessDecision(
                is_stale=is_stale,
                should_refresh=False,
                requests_official_refresh=False,
                next_refresh_at=next_refresh_at,
                reason="pending_fetch",
            )

        if beatmap.metadata_fetch_state is BeatmapFetchState.FAILED:
            return BeatmapFreshnessDecision(
                is_stale=is_stale,
                should_refresh=True,
                requests_official_refresh=official_sources_available
                and _is_mirror_sourced(beatmap),
                next_refresh_at=next_refresh_at,
                reason="failed_fetch",
            )

        if official_sources_available and _is_mirror_sourced(beatmap):
            return BeatmapFreshnessDecision(
                is_stale=True,
                should_refresh=True,
                requests_official_refresh=True,
                next_refresh_at=next_refresh_at,
                reason="mirror_official_refresh_due",
            )

        if is_stale:
            return BeatmapFreshnessDecision(
                is_stale=True,
                should_refresh=True,
                requests_official_refresh=official_sources_available
                and _is_mirror_sourced(beatmap),
                next_refresh_at=next_refresh_at,
                reason="stale",
            )

        return BeatmapFreshnessDecision(
            is_stale=False,
            should_refresh=False,
            requests_official_refresh=False,
            next_refresh_at=next_refresh_at,
            reason=None,
        )

    def _effective_next_refresh_at(self, beatmap: Beatmap) -> datetime | None:
        """保存済みまたはpolicy導出の次回refresh日時を選ぶ.

        Args:
            beatmap (Beatmap): refresh日時を取得するbeatmap.

        Returns:
            datetime | None: 有効な保存済みnext_refresh_at. 不在またはlast_fetched_at以下なら
                policy導出値.
        """
        if beatmap.last_fetched_at is None:
            return beatmap.next_refresh_at
        if beatmap.next_refresh_at is None:
            return self._derive_next_refresh_at(beatmap)
        if beatmap.next_refresh_at <= beatmap.last_fetched_at:
            return self._derive_next_refresh_at(beatmap)
        return beatmap.next_refresh_at

    def _derive_next_refresh_at(self, beatmap: Beatmap) -> datetime | None:
        """取得時刻,source,採用statusから次回refresh日時を導出する.

        Args:
            beatmap (Beatmap): refresh日時を導出するbeatmap.

        Returns:
            datetime | None: last_fetched_atに適切なintervalを加えた日時. 未取得ならNone.

        Notes:
            mirror由来recordはstatusにかかわらずmirror_refresh_intervalを使用する.
        """
        if beatmap.last_fetched_at is None:
            return None

        if _is_mirror_sourced(beatmap):
            return beatmap.last_fetched_at + self.mirror_refresh_interval

        status = beatmap.effective_status
        if status in _STABLE_STATUSES:
            return beatmap.last_fetched_at + self.ranked_refresh_interval
        if status in _PENDING_LIKE_STATUSES:
            return beatmap.last_fetched_at + self.pending_refresh_interval
        if status is BeatmapRankStatus.GRAVEYARD:
            return beatmap.last_fetched_at + self.graveyard_refresh_interval
        return beatmap.last_fetched_at + self.pending_refresh_interval
