"""Stable user status state store protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.compatibility.stable import StableUserStatus


@runtime_checkable
class StableUserStatusStore(Protocol):
    """Stable client の current status から必要な状態を保持する protocol。"""

    async def set_status(self, user_id: int, status: StableUserStatus) -> None:
        """指定 user の current status fields を保存する。"""
        ...

    async def get_statuses(
        self,
        user_ids: tuple[int, ...],
    ) -> dict[int, StableUserStatus]:
        """複数 user の current status fields を user id keyed mapping で返す。"""
        ...

    async def set_play_mode(self, user_id: int, play_mode: int) -> None:
        """指定 user の current play mode を保存する。"""
        ...

    async def get_play_mode(self, user_id: int) -> int | None:
        """指定 user の current play mode を返す。未保存なら None を返す。"""
        ...

    async def get_play_modes(self, user_ids: tuple[int, ...]) -> dict[int, int]:
        """複数 user の current play mode を user id keyed mapping で返す。"""
        ...

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """保存済み status の TTL を session TTL と同期する。"""
        ...


__all__ = ["StableUserStatusStore"]
