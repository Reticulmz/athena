"""ScoreRepository Protocol — abstract interface for score persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.score.score import Score


@runtime_checkable
class ScoreRepository(Protocol):
    """Protocol for score CRUD operations and uniqueness enforcement.

    Preconditions:
        - ``online_checksum`` must be globally unique across all scores.
    Postconditions:
        - ``create()`` returns a ``Score`` with an auto-generated ``id``.
    """

    async def create(self, score: Score) -> Score:
        """Persist a new score and return it with a generated id.

        Raises ``ValueError`` if ``online_checksum`` already exists.
        """
        ...

    async def exists_by_online_checksum(self, checksum: str) -> bool:
        """Return ``True`` if a score with *checksum* exists."""
        ...

    async def get_by_id(self, score_id: int) -> Score | None:
        """Return the score with *score_id*, or ``None`` if not found."""
        ...
