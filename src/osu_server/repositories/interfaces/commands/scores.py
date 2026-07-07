"""Command-side score repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Playstyle, Ruleset, Score
    from osu_server.repositories.interfaces.commands.beatmaps import BeatmapSubmissionCounts


@runtime_checkable
class ScoreCommandRepository(Protocol):
    """Mutation and consistency-check port for score ingestion."""

    async def create(self, score: Score) -> Score:
        """Persist a score and return it with repository-assigned identity."""
        ...

    async def exists_by_online_checksum(self, checksum: str) -> bool:
        """Return whether the score checksum already exists."""
        ...

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        """Return a score by checksum for idempotency checks."""
        ...

    async def get_by_id(self, score_id: int) -> Score | None:
        """Return a score by identifier for command-side consistency checks."""
        ...

    async def increment_replay_view_count(self, score_id: int) -> bool:
        """対象 score の Replay View Count を 1 増やし、存在したか返す。"""
        ...

    async def count_submissions_for_beatmap(self, beatmap_id: int) -> BeatmapSubmissionCounts:
        """Return cumulative submitted play/pass count for one beatmap."""
        ...

    async def list_current_stats_scores_for_user(
        self,
        user_id: int,
        *,
        ruleset: Ruleset,
        playstyle: Playstyle,
    ) -> tuple[Score, ...]:
        """Return source scores used to rebuild one user's current UserStats projection."""
        ...

    async def list_leaderboard_rebuild_candidates_for_user(
        self,
        user_id: int,
    ) -> tuple[Score, ...]:
        """Return eligible source scores for rebuilding one user's leaderboard slice."""
        ...

    async def list_leaderboard_rebuild_candidates_for_beatmap_ids(
        self,
        beatmap_ids: tuple[int, ...],
    ) -> tuple[Score, ...]:
        """Return eligible source scores for rebuilding one beatmap projection slice."""
        ...
