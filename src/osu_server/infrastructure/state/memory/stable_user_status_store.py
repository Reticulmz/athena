"""Stable user status state store の in-memory 実装を提供する module."""

from __future__ import annotations

from osu_server.domain.compatibility.stable import (
    DEFAULT_STABLE_USER_STATUS,
    StableUserStatus,
)


class InMemoryStableUserStatusStore:
    """Stable current status を process local memory で保持する state store.

    Attributes:
        _statuses_by_user_id (dict[int, StableUserStatus]): user id ごとの current stable status.

    Notes:
        TTL expiration を計測しないため、test と in-memory runtime 用の double として使う.
    """

    def __init__(self) -> None:
        """空の stable status storage を初期化する.

        Returns:
            None: 空の state store instance を初期化したことを表す.
        """
        self._statuses_by_user_id: dict[int, StableUserStatus] = {}

    async def set_status(self, user_id: int, status: StableUserStatus) -> None:
        """User の current stable status を保存する.

        Args:
            user_id (int): 保存先 user id.
            status (StableUserStatus): 保存する stable client status.

        Returns:
            None: status 保存処理の完了を表す.
        """
        self._statuses_by_user_id[user_id] = status

    async def get_statuses(
        self,
        user_ids: tuple[int, ...],
    ) -> dict[int, StableUserStatus]:
        """複数 user の current stable status を user id keyed mapping で返す.

        Args:
            user_ids (tuple[int, ...]): 取得対象の user id 群.

        Returns:
            dict[int, StableUserStatus]: 保存済み user id だけを含む status mapping.
        """
        return {
            user_id: status
            for user_id in user_ids
            if (status := self._statuses_by_user_id.get(user_id)) is not None
        }

    async def set_play_mode(self, user_id: int, play_mode: int) -> None:
        """User の current play mode を保存する.

        Args:
            user_id (int): 保存先 user id.
            play_mode (int): stable protocol の current play mode 値.

        Returns:
            None: play mode 保存処理の完了を表す.

        Notes:
            status が未保存なら DEFAULT_STABLE_USER_STATUS を基準に作成する.
        """
        current = self._statuses_by_user_id.get(user_id, DEFAULT_STABLE_USER_STATUS)
        self._statuses_by_user_id[user_id] = current.with_play_mode(play_mode)

    async def get_play_mode(self, user_id: int) -> int | None:
        """User の current play mode を返す.

        Args:
            user_id (int): 取得対象の user id.

        Returns:
            int | None: 保存済み play mode。status が未保存なら None.
        """
        status = self._statuses_by_user_id.get(user_id)
        return None if status is None else status.play_mode

    async def get_play_modes(self, user_ids: tuple[int, ...]) -> dict[int, int]:
        """複数 user の current play mode を user id keyed mapping で返す.

        Args:
            user_ids (tuple[int, ...]): 取得対象の user id 群.

        Returns:
            dict[int, int]: 保存済み user id だけを含む play mode mapping.
        """
        return {
            user_id: status.play_mode
            for user_id in user_ids
            if (status := self._statuses_by_user_id.get(user_id)) is not None
        }

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """Protocol 互換の TTL refresh を no-op として受け取る.

        Args:
            user_id (int): refresh 対象の user id。memory 実装では使用しない.
            ttl (int): session と同期する TTL 秒数。memory 実装では使用しない.

        Returns:
            None: no-op refresh の完了を表す.

        Notes:
            保存済み status の有無と expiration は変更しない.
        """
        _ = (user_id, ttl)


__all__ = ["InMemoryStableUserStatusStore"]
