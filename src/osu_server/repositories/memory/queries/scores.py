"""In-memory query-side score repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Score
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryScoreQueryRepository:
    """Read-only score repository over committed memory state."""

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def get_by_id(self, score_id: int) -> Score | None:
        state = self._factory.snapshot()
        return state.scores_by_id.get(score_id)

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        state = self._factory.snapshot()
        score_id = state.score_id_by_online_checksum.get(checksum)
        if score_id is None:
            return None
        return state.scores_by_id.get(score_id)
