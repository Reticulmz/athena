"""In-memory command-side replay repository."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.replay import Replay
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryReplayCommandRepository:
    """Replay command repository backed by an active in-memory UoW state."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    async def create(self, replay: Replay) -> Replay:
        if replay.checksum_sha256 in self._state.replay_id_by_checksum:
            msg = f"checksum_sha256 already exists: {replay.checksum_sha256}"
            raise ValueError(msg)

        created = replace(replay, id=self._state.next_replay_id)
        assert created.id is not None
        self._state.next_replay_id += 1
        self._state.replays_by_id[created.id] = created
        self._state.replay_id_by_checksum[created.checksum_sha256] = created.id
        return created

    async def exists_by_checksum(self, checksum: str) -> bool:
        return checksum in self._state.replay_id_by_checksum
