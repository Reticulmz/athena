"""Query-side score repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Score


class ScoreQueryRepository(Protocol):
    """Read-only score access for display and compatibility workflows."""

    async def get_by_id(self, score_id: int) -> Score | None:
        """Return the score with the identifier."""
        ...

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        """Return the score with the online checksum."""
        ...
