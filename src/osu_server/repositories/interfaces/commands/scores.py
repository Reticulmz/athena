"""Command-side score repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Score


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
