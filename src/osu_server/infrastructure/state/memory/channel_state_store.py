"""チャンネル参加状態の in-memory 実装を提供する module."""

from __future__ import annotations


class InMemoryChannelStateStore:
    """チャンネル参加状態を process local memory で保持する state store.

    Attributes:
        _channel_members (dict[str, set[int]]): チャンネル名から参加 user id 集合への index.
        _user_channels (dict[int, set[str]]): user id から参加チャンネル名集合への index.

    Notes:
        channel -> members と user -> channels を常に同時に更新する.
        thread-safe ではなく,single-threaded test environment 向けに限定する.
    """

    def __init__(self) -> None:
        """空の双方向チャンネル参加 index を初期化する."""
        self._channel_members: dict[str, set[int]] = {}
        self._user_channels: dict[int, set[str]] = {}

    async def add_member(self, channel_name: str, user_id: int) -> None:
        """User をチャンネルへ参加させる.

        Args:
            channel_name (str): 参加先のチャンネル名.
            user_id (int): 参加させる user id.

        Returns:
            None: 両方の参加indexを更新し, 呼び出し側へ値を返さずに終了する.

        Notes:
            既に参加済みの場合は状態を変えず成功する.
        """
        self._channel_members.setdefault(channel_name, set()).add(user_id)
        self._user_channels.setdefault(user_id, set()).add(channel_name)

    async def remove_member(self, channel_name: str, user_id: int) -> None:
        """User をチャンネルから退会させる.

        Args:
            channel_name (str): 退会元のチャンネル名.
            user_id (int): 退会させる user id.

        Returns:
            None: 両方の参加indexを更新し, 呼び出し側へ値を返さずに終了する.

        Notes:
            未参加の場合は状態を変えず成功し,空になった index entry は削除する.
        """
        members = self._channel_members.get(channel_name)
        if members is not None:
            members.discard(user_id)
            if not members:
                del self._channel_members[channel_name]

        channels = self._user_channels.get(user_id)
        if channels is not None:
            channels.discard(channel_name)
            if not channels:
                del self._user_channels[user_id]

    async def is_member(self, channel_name: str, user_id: int) -> bool:
        """User がチャンネルに参加しているかを返す.

        Args:
            channel_name (str): 確認するチャンネル名.
            user_id (int): 確認する user id.

        Returns:
            bool: 参加していれば True,そうでなければ False.
        """
        members = self._channel_members.get(channel_name)
        if members is None:
            return False
        return user_id in members

    async def get_members(self, channel_name: str) -> set[int]:
        """チャンネルに参加している user id のコピーを返す.

        Args:
            channel_name (str): 取得するチャンネル名.

        Returns:
            set[int]: 参加 user id の独立した集合.未存在または空なら空集合.
        """
        return set(self._channel_members.get(channel_name, set()))

    async def get_member_count(self, channel_name: str) -> int:
        """チャンネルの参加者数を返す.

        Args:
            channel_name (str): 件数を取得するチャンネル名.

        Returns:
            int: 現在の参加者数.チャンネルが未存在なら 0.
        """
        members = self._channel_members.get(channel_name)
        if members is None:
            return 0
        return len(members)

    async def get_user_channels(self, user_id: int) -> set[str]:
        """User が参加しているチャンネル名のコピーを返す.

        Args:
            user_id (int): 参加チャンネルを取得する user id.

        Returns:
            set[str]: 参加チャンネル名の独立した集合.未参加なら空集合.
        """
        return set(self._user_channels.get(user_id, set()))

    async def remove_user_from_all(self, user_id: int) -> set[str]:
        """User を参加中のすべてのチャンネルから退会させる.

        Args:
            user_id (int): 全参加状態を削除する user id.

        Returns:
            set[str]: 削除したチャンネル名の独立した集合.未参加なら空集合.
        """
        channels = self._user_channels.pop(user_id, set())
        for channel_name in channels:
            members = self._channel_members.get(channel_name)
            if members is not None:
                members.discard(user_id)
                if not members:
                    del self._channel_members[channel_name]
        return set(channels)
