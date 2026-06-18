"""In-memory command-side score repository."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Score
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryScoreCommandRepository:
    """Score command repository backed by an active in-memory UoW state."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    async def create(self, score: Score) -> Score:
        if score.online_checksum in self._state.score_id_by_online_checksum:
            msg = f"online_checksum already exists: {score.online_checksum}"
            raise ValueError(msg)

        created = replace(score, id=self._state.next_score_id)
        assert created.id is not None
        self._state.next_score_id += 1
        self._state.scores_by_id[created.id] = created
        self._state.score_id_by_online_checksum[created.online_checksum] = created.id
        self._state.score_leaderboard_eligibility_by_id[created.id] = (
            created.leaderboard_eligible_at_submission
        )
        return created

    async def exists_by_online_checksum(self, checksum: str) -> bool:
        return checksum in self._state.score_id_by_online_checksum

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        score_id = self._state.score_id_by_online_checksum.get(checksum)
        if score_id is None:
            return None
        return self._state.scores_by_id.get(score_id)

    async def get_by_id(self, score_id: int) -> Score | None:
        return self._state.scores_by_id.get(score_id)
