"""In-memory command 側 replay repository を実装する module."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.replay import Replay
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryReplayCommandRepository:
    """Replay primary record と checksum index を command 用に管理する.

    Attributes:
        _state (InMemoryCommandRepositoryState): 所有 Unit of Work の可変 state snapshot.

    Notes:
        この repository は lock 又は thread synchronization を提供しない. 同じ state を
        複数 task 又は thread から同時に変更してはならない.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """Active Unit of Work の state snapshot を保持する.

        Args:
            state (InMemoryCommandRepositoryState): repository が直接読み書きする state.

        Returns:
            None: state への参照を保持したことを示す.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def create(self, replay: Replay) -> Replay:
        """一意な SHA-256 checksum を持つ replay を作成し ID を割り当てる.

        Args:
            replay (Replay): 保存する replay. 入力 ID は保存時に置き換える.

        Returns:
            Replay: next_replay_id を割り当てて保存した replay.

        Raises:
            ValueError: replay.checksum_sha256 が checksum index にすでに存在する場合.

        Notes:
            成功時は next_replay_id, 主記録, checksum index を更新する.
        """
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
        """Replay checksum が checksum index に存在するか返す.

        Args:
            checksum (str): 存在確認する replay checksum.

        Returns:
            bool: checksum index に key が存在する場合は True.
        """
        return checksum in self._state.replay_id_by_checksum
