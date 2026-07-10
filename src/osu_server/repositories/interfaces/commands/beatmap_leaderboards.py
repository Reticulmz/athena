"""Command-side beatmap leaderboard projection repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.scores.leaderboards import ALL_MODS_FILTER_KEY

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.scores.leaderboards import ScoreRankKey
    from osu_server.domain.scores.score import Playstyle, Ruleset


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardUserBestScope:
    """Natural key for one user's representative score inside a leaderboard scope."""

    beatmap_id: int
    ruleset: Ruleset
    playstyle: Playstyle
    user_id: int
    mod_filter_key: int

    def __post_init__(self) -> None:
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)
        if self.mod_filter_key < ALL_MODS_FILTER_KEY:
            msg = "mod_filter_key must be all-mods sentinel or non-negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardUserBest:
    """Persisted score-priority projection row for one user and scope."""

    id: int | None
    scope: BeatmapLeaderboardUserBestScope
    score_id: int
    rank_key: ScoreRankKey

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            msg = "id must be positive when present"
            raise ValueError(msg)
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)
        if self.rank_key.score_id != self.score_id:
            msg = "rank_key score_id must match score_id"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class UpsertBeatmapLeaderboardUserBest:
    """Create or replace a projection row if the candidate ranks higher."""

    scope: BeatmapLeaderboardUserBestScope
    score_id: int
    rank_key: ScoreRankKey

    def __post_init__(self) -> None:
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)
        if self.rank_key.score_id != self.score_id:
            msg = "rank_key score_id must match score_id"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardUserProjectionSlice:
    """Projection slice rebuilt for a single user."""

    user_id: int

    def __post_init__(self) -> None:
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardBeatmapProjectionSlice:
    """Projection slice rebuilt for one or more beatmaps."""

    beatmap_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.beatmap_ids) == 0:
            msg = "beatmap_ids must not be empty"
            raise ValueError(msg)
        if any(beatmap_id <= 0 for beatmap_id in self.beatmap_ids):
            msg = "beatmap_ids must be positive"
            raise ValueError(msg)


type BeatmapLeaderboardProjectionSlice = (
    BeatmapLeaderboardUserProjectionSlice | BeatmapLeaderboardBeatmapProjectionSlice
)


class BeatmapLeaderboardCommandRepository(Protocol):
    """Mutation and consistency-check port for beatmap leaderboard projections."""

    async def get_user_best(
        self,
        scope: BeatmapLeaderboardUserBestScope,
    ) -> BeatmapLeaderboardUserBest | None:
        """Return the current representative score for one user and scope."""
        ...

    async def upsert_if_better(
        self,
        command: UpsertBeatmapLeaderboardUserBest,
    ) -> BeatmapLeaderboardUserBest:
        """Persist the candidate if it ranks above the current representative."""
        ...

    async def replace_projection_slice(
        self,
        slice_: BeatmapLeaderboardProjectionSlice,
        rows: Iterable[UpsertBeatmapLeaderboardUserBest],
    ) -> None:
        """Replace all projection rows in a rebuilt slice with the supplied rows."""
        ...
