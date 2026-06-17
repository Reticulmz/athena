"""Command-side personal best projection repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.personal_best import PersonalBest, PersonalBestScope


@dataclass(frozen=True, slots=True)
class UpsertPersonalBest:
    """Create or replace a personal best projection if the candidate wins."""

    scope: PersonalBestScope
    score_id: int
    ranking_value: int

    def __post_init__(self) -> None:
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)
        if self.ranking_value < 0:
            msg = "ranking_value must not be negative"
            raise ValueError(msg)


class PersonalBestCommandRepository(Protocol):
    """Mutation and consistency-check port for personal best projections."""

    async def get_by_scope(self, scope: PersonalBestScope) -> PersonalBest | None:
        """Return the current personal best for one scope."""
        ...

    async def upsert_if_better(self, command: UpsertPersonalBest) -> PersonalBest:
        """Persist the candidate if it beats the current personal best."""
        ...
