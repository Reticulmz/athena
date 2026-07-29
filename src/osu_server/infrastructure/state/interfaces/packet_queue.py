"""Stable client 向け S2C packet queue の抽象 contract を定義する module."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PacketQueue(Protocol):
    """User ごとの S2C packet queue を扱う contract.

    Notes:
        refresh_ttl により有効な session を表す queue だけが enqueue を受け付ける.
        queue は TTL と size upper bound を実装側の状態として管理する.
    """

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        """構築済み S2C packet を user の queue に追加する.

        Args:
            user_id (int): 追加先 queue を持つ user id.
            *data (bytes): 個別の S2C packet.複数指定時は同じ順序で追加する.

        Returns:
            None: enqueue 処理の完了を表す.

        Notes:
            有効な session がない user の packet は破棄する.
            size upper bound を超える場合は最も古い packet から切り捨てる.
        """
        ...

    async def dequeue_all(self, user_id: int) -> bytes:
        """Queue 全体を drain し,packet を連結した bytes を返す.

        Args:
            user_id (int): drain 対象 queue の user id.

        Returns:
            bytes: queue 内 packet を連結した値.空または未存在なら b"".

        Notes:
            正常に返った後の queue は空になる.
        """
        ...

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """Queue の TTL を更新し,session に対応する queue を有効化する.

        Args:
            user_id (int): 更新する queue の user id.
            ttl (int): session と同期する有効期限の秒数.

        Returns:
            None: TTL 更新処理の完了を表す.

        Notes:
            呼出側は session TTL を更新する同じタイミングで呼び出す.
        """
        ...
