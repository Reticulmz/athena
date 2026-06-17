"""Query-side Beatmap Leaderboard repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from osu_server.domain.scores.mods import ModCombination
    from osu_server.domain.scores.personal_best import LeaderboardCategory
    from osu_server.domain.scores.score import Playstyle, Ruleset


@dataclass(slots=True, frozen=True)
class ScoreHitCounts:
    """Display hit counts copied from the source Score."""

    n50: int
    n100: int
    n300: int
    miss: int
    katu: int
    geki: int


@dataclass(slots=True, frozen=True)
class BeatmapLeaderboardRow:
    """Display-ready row for a Beatmap Leaderboard listing."""

    score_id: int
    user_id: int
    username: str
    beatmap_id: int
    ruleset: Ruleset
    playstyle: Playstyle
    score: int
    max_combo: int
    hit_counts: ScoreHitCounts
    perfect: bool
    displayed_mods: ModCombination
    rank: int
    submitted_at: datetime
    has_replay: bool
    pp: Decimal | None = None


@dataclass(slots=True, frozen=True)
class LeaderboardReadScope:
    """Read-time filters for one Beatmap Leaderboard query."""

    beatmap_id: int
    beatmap_checksum: str
    ruleset: Ruleset
    playstyle: Playstyle
    category: LeaderboardCategory
    mod_filter_key: int | None
    country: str | None = None
    eligible_user_ids: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)
        if self.mod_filter_key is not None and self.mod_filter_key < 0:
            msg = "mod_filter_key must not be negative"
            raise ValueError(msg)


class BeatmapLeaderboardQueryRepository(Protocol):
    """Read-only Beatmap Leaderboard projection access."""

    async def list_top_rows(
        self,
        scope: LeaderboardReadScope,
        *,
        limit: int,
    ) -> tuple[BeatmapLeaderboardRow, ...]:
        """Return ranked top rows for the filtered scope."""
        ...

    async def get_personal_best(
        self,
        scope: LeaderboardReadScope,
        *,
        viewer_user_id: int,
    ) -> BeatmapLeaderboardRow | None:
        """Return the viewer's row with actual rank inside the filtered scope."""
        ...


__all__ = [
    "BeatmapLeaderboardQueryRepository",
    "BeatmapLeaderboardRow",
    "LeaderboardReadScope",
    "ScoreHitCounts",
]
