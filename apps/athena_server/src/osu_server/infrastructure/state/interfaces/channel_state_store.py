"""チャンネル参加状態を扱う抽象 contract を定義する module."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ChannelStateStore(Protocol):
    """チャンネルと user の参加状態を双方向 index として管理する contract.

    Notes:
        実装は channel -> members と user -> channels を同じ論理状態として更新する.
        追加と削除は冪等であり,存在しない参加状態への操作を失敗にしない.
    """

    async def add_member(self, channel_name: str, user_id: int) -> None:
        """User をチャンネルへ参加させ,両方の index を更新する.

        Args:
            channel_name (str): 参加先のチャンネル名.
            user_id (int): 参加させる user id.

        Returns:
            None: 参加状態の更新完了を表す.

        Notes:
            既に参加済みの場合は状態を変えず成功する.
        """
        ...

    async def remove_member(self, channel_name: str, user_id: int) -> None:
        """User をチャンネルから退会させ,両方の index を更新する.

        Args:
            channel_name (str): 退会元のチャンネル名.
            user_id (int): 退会させる user id.

        Returns:
            None: 参加状態の更新完了を表す.

        Notes:
            未参加の場合は状態を変えず成功する.
        """
        ...

    async def is_member(self, channel_name: str, user_id: int) -> bool:
        """User がチャンネルに参加しているかを返す.

        Args:
            channel_name (str): 確認するチャンネル名.
            user_id (int): 確認する user id.

        Returns:
            bool: 参加していれば True,そうでなければ False.
        """
        ...

    async def get_members(self, channel_name: str) -> set[int]:
        """チャンネルに参加している user id の集合を返す.

        Args:
            channel_name (str): 取得するチャンネル名.

        Returns:
            set[int]: 現在の参加 user id.チャンネルが未存在または空なら空集合.
        """
        ...

    async def get_member_count(self, channel_name: str) -> int:
        """チャンネルの参加者数を返す.

        Args:
            channel_name (str): 件数を取得するチャンネル名.

        Returns:
            int: 現在の参加者数.チャンネルが未存在なら 0.
        """
        ...

    async def get_user_channels(self, user_id: int) -> set[str]:
        """User が参加しているチャンネル名の集合を返す.

        Args:
            user_id (int): 参加チャンネルを取得する user id.

        Returns:
            set[str]: 現在のチャンネル名.参加状態がなければ空集合.
        """
        ...

    async def remove_user_from_all(self, user_id: int) -> set[str]:
        """User を参加中の全チャンネルから退会させる.

        Args:
            user_id (int): 全参加状態を削除する user id.

        Returns:
            set[str]: 削除したチャンネル名.参加状態がなければ空集合.
        """
        ...
