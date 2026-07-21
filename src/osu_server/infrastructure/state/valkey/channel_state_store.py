"""チャンネル参加状態の Valkey 実装を提供する module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from glide import Batch

if TYPE_CHECKING:
    from glide import GlideClient


class ValkeyChannelStateStore:
    """チャンネル参加状態を Valkey Set の双方向 index として管理する state store.

    Attributes:
        _client (GlideClient): Set 操作と atomic batch を実行する Valkey client.
        _prefix (str): 環境または test を分離する key prefix.

    Notes:
        channel key は `{prefix}channel:{name}:members`、user key は
        `{prefix}user:{user_id}:channels` を使用する.
        両方の index は Batch(is_atomic=True) で更新し、TTL は設定しない.
    """

    def __init__(self, client: GlideClient, *, key_prefix: str = "") -> None:
        """Valkey client と key prefix を持つ state store を初期化する.

        Args:
            client (GlideClient): Set 操作と batch 実行を提供する Valkey client.
            key_prefix (str): key 名前空間を分離する任意の prefix.

        Returns:
            None: state store instance を初期化したことを表す.
        """
        self._client: GlideClient = client
        self._prefix: str = key_prefix

    # -- key helpers ----------------------------------------------------------

    def _channel_key(self, channel_name: str) -> str:
        """チャンネルの member Set に対応する Valkey key を組み立てる.

        Args:
            channel_name (str): key に埋め込むチャンネル名.

        Returns:
            str: `{prefix}channel:{channel_name}:members` 形式の member Set key.
        """
        return f"{self._prefix}channel:{channel_name}:members"

    def _user_key(self, user_id: int) -> str:
        """User の channel Set に対応する Valkey key を組み立てる.

        Args:
            user_id (int): key に埋め込む user id.

        Returns:
            str: `{prefix}user:{user_id}:channels` 形式の channel Set key.
        """
        return f"{self._prefix}user:{user_id}:channels"

    # -- ChannelStateStore Protocol methods -----------------------------------

    async def add_member(self, channel_name: str, user_id: int) -> None:
        """User をチャンネルへ参加させ、双方向 Set を atomic に更新する.

        Args:
            channel_name (str): 参加先のチャンネル名.
            user_id (int): 参加させる user id.

        Returns:
            None: atomic batch の実行完了を表す.

        Notes:
            SADD の冪等性により、既に参加済みの場合も成功する.
        """
        batch = Batch(is_atomic=True)
        _ = batch.sadd(self._channel_key(channel_name), [str(user_id)])
        _ = batch.sadd(self._user_key(user_id), [channel_name])
        _ = await self._client.exec(batch, raise_on_error=True)

    async def remove_member(self, channel_name: str, user_id: int) -> None:
        """User をチャンネルから退会させ、双方向 Set を atomic に更新する.

        Args:
            channel_name (str): 退会元のチャンネル名.
            user_id (int): 退会させる user id.

        Returns:
            None: atomic batch の実行完了を表す.

        Notes:
            SREM の冪等性により、未参加の場合も成功する.
        """
        batch = Batch(is_atomic=True)
        _ = batch.srem(self._channel_key(channel_name), [str(user_id)])
        _ = batch.srem(self._user_key(user_id), [channel_name])
        _ = await self._client.exec(batch, raise_on_error=True)

    async def is_member(self, channel_name: str, user_id: int) -> bool:
        """User がチャンネルの member Set に含まれるかを返す.

        Args:
            channel_name (str): 確認するチャンネル名.
            user_id (int): 確認する user id.

        Returns:
            bool: member Set に含まれる場合は True、そうでなければ False.
        """
        return await self._client.sismember(self._channel_key(channel_name), str(user_id))

    async def get_members(self, channel_name: str) -> set[int]:
        """チャンネルの member Set を user id 集合へ復元して返す.

        Args:
            channel_name (str): 取得するチャンネル名.

        Returns:
            set[int]: 現在の参加 user id。key が未存在なら空集合.
        """
        raw = await self._client.smembers(self._channel_key(channel_name))
        return {int(m) for m in raw}

    async def get_member_count(self, channel_name: str) -> int:
        """チャンネルの member Set に含まれる user 数を返す.

        Args:
            channel_name (str): 件数を取得するチャンネル名.

        Returns:
            int: 現在の参加者数。key が未存在なら 0.
        """
        return await self._client.scard(self._channel_key(channel_name))

    async def get_user_channels(self, user_id: int) -> set[str]:
        """User の channel Set をチャンネル名集合として返す.

        Args:
            user_id (int): 取得する user id.

        Returns:
            set[str]: 現在の参加チャンネル名。key が未存在なら空集合.
        """
        raw = await self._client.smembers(self._user_key(user_id))
        return {m.decode() for m in raw}

    async def remove_user_from_all(self, user_id: int) -> set[str]:
        """User を参加中の全チャンネルから退会させ、削除結果を返す.

        Args:
            user_id (int): 全参加状態を削除する user id.

        Returns:
            set[str]: 削除したチャンネル名。参加状態がなければ空集合.

        Notes:
            取得した全 channel member Set と user channel Set を同じ atomic batch で更新する.
        """
        user_key = self._user_key(user_id)
        raw = await self._client.smembers(user_key)
        if not raw:
            return set()

        channel_names = {m.decode() for m in raw}

        batch = Batch(is_atomic=True)
        for channel_name in channel_names:
            _ = batch.srem(self._channel_key(channel_name), [str(user_id)])
        _ = batch.delete([user_key])
        _ = await self._client.exec(batch, raise_on_error=True)

        return channel_names
