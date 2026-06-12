"""InMemoryScoreRepository — dict-based score repository for testing."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.score.score import Score


class InMemoryScoreRepository:
    """In-memory implementation of the ScoreRepository Protocol.

    Uses plain dicts for storage with auto-incrementing id.
    Not thread-safe — intended for single-threaded test environments only.
    """

    def __init__(self) -> None:
        self._scores_by_id: dict[int, Score] = {}
        self._id_by_online_checksum: dict[str, int] = {}
        self._next_id: int = 1

    async def create(self, score: Score) -> Score:
        """Persist a new score and return it with a generated id.

        Raises ``ValueError`` if ``online_checksum`` already exists.
        """
        if score.online_checksum in self._id_by_online_checksum:
            msg = f"online_checksum already exists: {score.online_checksum}"
            raise ValueError(msg)

        created = replace(score, id=self._next_id)
        self._next_id += 1

        self._scores_by_id[created.id] = created  # pyright: ignore[reportArgumentType]
        self._id_by_online_checksum[created.online_checksum] = created.id  # pyright: ignore[reportArgumentType]

        return created

    async def exists_by_online_checksum(self, checksum: str) -> bool:
        """Return ``True`` if a score with *checksum* exists."""
        return checksum in self._id_by_online_checksum

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        """Return the score with *checksum*, or ``None`` if not found."""
        score_id = self._id_by_online_checksum.get(checksum)
        if score_id is None:
            return None
        return self._scores_by_id.get(score_id)

    async def get_by_id(self, score_id: int) -> Score | None:
        """Return the score with *score_id*, or ``None`` if not found."""
        return self._scores_by_id.get(score_id)
