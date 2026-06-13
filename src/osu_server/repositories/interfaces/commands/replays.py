"""Command-side replay repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.replay import Replay


class ReplayCommandRepository(Protocol):
    """Mutation and uniqueness-check port for score replays."""

    async def create(self, replay: Replay) -> Replay:
        """Persist a replay and return it with repository-assigned identity."""
        ...

    async def exists_by_checksum(self, checksum: str) -> bool:
        """Return whether a replay with the checksum already exists."""
        ...
