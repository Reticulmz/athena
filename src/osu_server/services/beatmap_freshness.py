from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from osu_server.domain.beatmap import BeatmapFetchState, BeatmapMetadataSource, BeatmapRankStatus

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from osu_server.domain.beatmap import Beatmap

_STABLE_STATUSES: Final = frozenset(
    {BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED, BeatmapRankStatus.LOVED}
)
_PENDING_LIKE_STATUSES: Final = frozenset(
    {BeatmapRankStatus.QUALIFIED, BeatmapRankStatus.PENDING, BeatmapRankStatus.WIP}
)


@dataclass(slots=True, frozen=True)
class BeatmapFreshnessDecision:
    is_stale: bool
    should_refresh: bool
    requests_official_refresh: bool
    next_refresh_at: datetime | None
    reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapFreshnessPolicy:
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
        next_refresh_at = beatmap.next_refresh_at or self._derive_next_refresh_at(beatmap)
        is_stale = next_refresh_at is not None and next_refresh_at <= now

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

    def _derive_next_refresh_at(self, beatmap: Beatmap) -> datetime | None:
        if beatmap.last_fetched_at is None:
            return None

        status = beatmap.effective_status
        if status in _STABLE_STATUSES:
            return beatmap.last_fetched_at + self.ranked_refresh_interval
        if status in _PENDING_LIKE_STATUSES:
            return beatmap.last_fetched_at + self.pending_refresh_interval
        if status is BeatmapRankStatus.GRAVEYARD:
            return beatmap.last_fetched_at + self.graveyard_refresh_interval
        return beatmap.last_fetched_at + self.pending_refresh_interval


def _is_mirror_sourced(beatmap: Beatmap) -> bool:
    return beatmap.official_status_source is BeatmapMetadataSource.MIRROR
