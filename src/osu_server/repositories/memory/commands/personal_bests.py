"""In-memory command-side personal best repository."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.domain.scores.personal_best import (
    PersonalBest,
    PersonalBestScope,
    score_beats_personal_best,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.commands.personal_bests import UpsertPersonalBest
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryPersonalBestCommandRepository:
    """Personal best command repository backed by an active in-memory UoW state."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    async def get_by_scope(self, scope: PersonalBestScope) -> PersonalBest | None:
        key = _scope_key(scope)
        personal_best_id = self._state.personal_best_id_by_scope.get(key)
        if personal_best_id is None:
            return None
        return self._state.personal_bests_by_id.get(personal_best_id)

    async def upsert_if_better(self, command: UpsertPersonalBest) -> PersonalBest:
        current = await self.get_by_scope(command.scope)
        if current is None:
            created = PersonalBest(
                id=self._state.next_personal_best_id,
                scope=command.scope,
                score_id=command.score_id,
                ranking_value=command.ranking_value,
            )
            assert created.id is not None
            self._state.next_personal_best_id += 1
            self._state.personal_bests_by_id[created.id] = created
            self._state.personal_best_id_by_scope[_scope_key(command.scope)] = created.id
            return created

        if not score_beats_personal_best(command.ranking_value, current.ranking_value):
            return current

        updated = replace(
            current,
            score_id=command.score_id,
            ranking_value=command.ranking_value,
        )
        assert updated.id is not None
        self._state.personal_bests_by_id[updated.id] = updated
        return updated


def _scope_key(scope: PersonalBestScope) -> tuple[int, int, int, int, str]:
    return (
        scope.user_id,
        scope.beatmap_id,
        scope.ruleset.value,
        scope.playstyle.value,
        scope.category.value,
    )
