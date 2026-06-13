"""InMemoryReplayRepository — dict-based replay repository for testing."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.replay import Replay


class InMemoryReplayRepository:
    """In-memory implementation of the ReplayRepository Protocol.

    Uses plain dicts for storage with auto-incrementing id.
    Not thread-safe — intended for single-threaded test environments only.
    """

    def __init__(self) -> None:
        self._replays_by_id: dict[int, Replay] = {}
        self._id_by_checksum: dict[str, int] = {}
        self._next_id: int = 1

    async def create(self, replay: Replay) -> Replay:
        """Persist a new replay and return it with a generated id.

        Raises ``ValueError`` if ``checksum_sha256`` already exists.
        """
        if replay.checksum_sha256 in self._id_by_checksum:
            msg = f"checksum_sha256 already exists: {replay.checksum_sha256}"
            raise ValueError(msg)

        created = replace(replay, id=self._next_id)
        self._next_id += 1

        self._replays_by_id[created.id] = created  # pyright: ignore[reportArgumentType]
        self._id_by_checksum[created.checksum_sha256] = created.id  # pyright: ignore[reportArgumentType]

        return created

    async def exists_by_checksum(self, checksum: str) -> bool:
        """Return ``True`` if a replay with *checksum* exists."""
        return checksum in self._id_by_checksum
