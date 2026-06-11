"""ReplayRepository Protocol — abstract interface for replay persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.score.replay import Replay


@runtime_checkable
class ReplayRepository(Protocol):
    """Protocol for replay CRUD operations and uniqueness enforcement.

    Preconditions:
        - ``checksum_sha256`` must be globally unique across all replays.
    Postconditions:
        - ``create()`` returns a ``Replay`` with an auto-generated ``id``.
    """

    async def create(self, replay: Replay) -> Replay:
        """Persist a new replay and return it with a generated id.

        Raises ``ValueError`` if ``checksum_sha256`` already exists.
        """
        ...

    async def exists_by_checksum(self, checksum: str) -> bool:
        """Return ``True`` if a replay with *checksum* exists."""
        ...
