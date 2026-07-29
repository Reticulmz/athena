"""S2C packet queue の in-memory 実装を提供する module."""

from __future__ import annotations


class InMemoryPacketQueue:
    """S2C packet queue を process local memory で保持する state store.

    Attributes:
        _queues (dict[int, list[bytes]]): user id ごとの活性化済み packet queue.
        _max_size (int): user ごとに保持する packet 数の上限.

    Notes:
        refresh_ttl を先に呼んだ user だけを active session として扱う.
        TTL 自体は memory では計測せず,thread-safe ではない test environment 向け実装である.
    """

    def __init__(self, max_size: int = 4096) -> None:
        """空の queue storage と packet 数上限を初期化する.

        Args:
            max_size (int): user ごとに保持する packet 数の上限.
        """
        self._queues: dict[int, list[bytes]] = {}
        self._max_size: int = max_size

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        """構築済み S2C packet を user の queue に追加する.

        Args:
            user_id (int): 追加先 queue を持つ user id.
            *data (bytes): 個別の S2C packet.複数指定時は同じ順序で追加する.

        Returns:
            None: enqueue 処理の完了を表す.

        Notes:
            data が空,または user に active session がない場合は何も追加しない.
            size upper bound を超える場合は最も古い packet から切り捨てる.
        """
        if not data:
            return
        queue = self._queues.get(user_id)
        if queue is None:
            return
        queue.extend(data)
        if len(queue) > self._max_size:
            del queue[: len(queue) - self._max_size]

    async def dequeue_all(self, user_id: int) -> bytes:
        """User の queue を drain し,packet を連結した bytes を返す.

        Args:
            user_id (int): drain 対象 queue の user id.

        Returns:
            bytes: queue 内 packet を連結した値.queue が空または未存在なら b"".

        Notes:
            正常に返った後の active queue は空になる.
        """
        queue = self._queues.get(user_id)
        if not queue:
            return b""
        result = b"".join(queue)
        queue.clear()
        return result

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
        """User の queue を active session として初期化する.

        Args:
            user_id (int): 活性化する queue の user id.
            ttl (int): protocol 互換の session TTL 秒数.memory 実装では保持しない.

        Returns:
            None: queue の活性化処理が完了したことを表す.

        Notes:
            既存 queue を消さず,TTL expiration は memory 実装では再現しない.
        """
        if user_id not in self._queues:
            self._queues[user_id] = []
