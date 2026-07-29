"""Stable user status を保存する抽象 state store contract を定義する module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.compatibility.stable import StableUserStatus


@runtime_checkable
class StableUserStatusStore(Protocol):
    """Stable client の current status と play mode を一時保存する contract.

    Notes:
        保存状態は session とともに失効する揮発状態であり,durable record ではない.
    """

    async def set_status(self, user_id: int, status: StableUserStatus) -> None:
        """User の current status fields を保存する.

        Args:
            user_id (int): 保存先 user id.
            status (StableUserStatus): 保存する stable client status.

        Returns:
            None: status 保存処理の完了を表す.
        """
        ...

    async def get_statuses(
        self,
        user_ids: tuple[int, ...],
    ) -> dict[int, StableUserStatus]:
        """複数 user の current status fields を user id keyed mapping で返す.

        Args:
            user_ids (tuple[int, ...]): 取得対象の user id 群.

        Returns:
            dict[int, StableUserStatus]: 保存済み user id だけを含む status mapping.
        """
        ...

    async def set_play_mode(self, user_id: int, play_mode: int) -> None:
        """User の current play mode を保存する.

        Args:
            user_id (int): 保存先 user id.
            play_mode (int): stable protocol の current play mode 値.

        Returns:
            None: play mode 保存処理の完了を表す.
        """
        ...

    async def get_play_mode(self, user_id: int) -> int | None:
        """User の current play mode を返す.

        Args:
            user_id (int): 取得対象の user id.

        Returns:
            int | None: 保存済み play mode.status が未保存なら None.
        """
        ...

    async def get_play_modes(self, user_ids: tuple[int, ...]) -> dict[int, int]:
        """複数 user の current play mode を user id keyed mapping で返す.

        Args:
            user_ids (tuple[int, ...]): 取得対象の user id 群.

        Returns:
            dict[int, int]: 保存済み user id だけを含む play mode mapping.
        """
        ...

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """保存済み status の TTL を session TTL と同期する.

        Args:
            user_id (int): TTL を更新する user id.
            ttl (int): session と同期する有効期限の秒数.

        Returns:
            None: TTL 更新処理の完了を表す.

        Notes:
            状態が未保存の場合に新しい status を作成しない.
        """
        ...


__all__ = ["StableUserStatusStore"]
