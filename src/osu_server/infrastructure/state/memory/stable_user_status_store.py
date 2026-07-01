"""In-memory stable user status store."""

from __future__ import annotations

from osu_server.domain.compatibility.stable import (
    DEFAULT_STABLE_USER_STATUS,
    StableUserStatus,
)


class InMemoryStableUserStatusStore:
    """Stable current status を in-memory で保持する test/runtime double。"""

    def __init__(self) -> None:
        self._statuses_by_user_id: dict[int, StableUserStatus] = {}

    async def set_status(self, user_id: int, status: StableUserStatus) -> None:
        """指定 user の current status fields を保存する。"""
        self._statuses_by_user_id[user_id] = status

    async def get_statuses(
        self,
        user_ids: tuple[int, ...],
    ) -> dict[int, StableUserStatus]:
        """複数 user の current status fields を返す。"""
        return {
            user_id: status
            for user_id in user_ids
            if (status := self._statuses_by_user_id.get(user_id)) is not None
        }

    async def set_play_mode(self, user_id: int, play_mode: int) -> None:
        """指定 user の current play mode を保存する。"""
        current = self._statuses_by_user_id.get(user_id, DEFAULT_STABLE_USER_STATUS)
        self._statuses_by_user_id[user_id] = current.with_play_mode(play_mode)

    async def get_play_mode(self, user_id: int) -> int | None:
        """指定 user の current play mode を返す。"""
        status = self._statuses_by_user_id.get(user_id)
        return None if status is None else status.play_mode

    async def get_play_modes(self, user_ids: tuple[int, ...]) -> dict[int, int]:
        """複数 user の current play mode を返す。"""
        return {
            user_id: status.play_mode
            for user_id in user_ids
            if (status := self._statuses_by_user_id.get(user_id)) is not None
        }

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """In-memory 実装では TTL を無視する。"""
        _ = (user_id, ttl)


__all__ = ["InMemoryStableUserStatusStore"]
