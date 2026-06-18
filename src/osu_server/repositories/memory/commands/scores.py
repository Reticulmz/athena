"""In-memory command-side score repository."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

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

    async def list_leaderboard_rebuild_candidates_for_user(
        self,
        user_id: int,
    ) -> tuple[Score, ...]:
        return tuple(
            sorted(
                (
                    score
                    for score in self._state.scores_by_id.values()
                    if score.user_id == user_id and _is_leaderboard_rebuild_candidate(score)
                ),
                key=_rebuild_candidate_sort_key,
            )
        )

    async def list_leaderboard_rebuild_candidates_for_beatmap_ids(
        self,
        beatmap_ids: tuple[int, ...],
    ) -> tuple[Score, ...]:
        beatmap_id_set = frozenset(beatmap_ids)
        if len(beatmap_id_set) == 0:
            return ()
        return tuple(
            sorted(
                (
                    score
                    for score in self._state.scores_by_id.values()
                    if score.beatmap_id in beatmap_id_set
                    and _is_leaderboard_rebuild_candidate(score)
                ),
                key=_rebuild_candidate_sort_key,
            )
        )


def _is_leaderboard_rebuild_candidate(score: Score) -> bool:
    return score.passed and score.leaderboard_eligible_at_submission and score.id is not None


def _rebuild_candidate_sort_key(score: Score) -> tuple[int, int, int, int, int, datetime, int]:
    assert score.id is not None
    return (
        score.beatmap_id,
        score.ruleset.value,
        score.playstyle.value,
        score.user_id,
        -score.score,
        score.submitted_at,
        score.id,
    )
