"""S2C packet queue の Valkey 実装を提供する module."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from glide import Script

if TYPE_CHECKING:
    from glide import GlideClient
    from glide_shared.constants import TEncodable


class ValkeyPacketQueue:
    """S2C packet queue を Valkey List と session marker で管理する state store.

    Attributes:
        _DEQUEUE_ALL_SCRIPT (ClassVar[Script]): packet List を atomic に読み出して削除する
            Lua script.
        _ENQUEUE_SCRIPT (ClassVar[Script]): active session を確認して packet を追加する Lua script.
        _REFRESH_SCRIPT (ClassVar[Script]): activation marker と既存 queue の TTL を更新する
            Lua script.
        _client (GlideClient): Lua script を実行する Valkey client.
        _max_size (int): user ごとに保持する packet 数の上限.
        _ttl (int): enqueue 時に queue key へ設定する TTL 秒数.
        _prefix (str): 環境または test を分離する key prefix.

    Notes:
        queue key は `{prefix}packet_queue:{user_id}`、activation key は
        `{prefix}pq_meta:{user_id}` を使用し、両方は同じ TTL を持つ.
        enqueue と dequeue_all は Lua script を使い、TOCTOU race を避ける.
    """

    # Lua script: atomically drain all packets from the queue.
    # KEYS[1] = packet_queue:{user_id}
    # Returns: list of packet bytes (empty list if queue is empty)
    _DEQUEUE_ALL_SCRIPT: ClassVar[Script] = Script("""\
local packets = redis.call('LRANGE', KEYS[1], 0, -1)
if #packets > 0 then
    redis.call('DEL', KEYS[1])
end
return packets""")

    # Lua script: atomically enqueue packets with size limit and TTL.
    # KEYS[1] = pq_meta:{user_id}  (activation flag)
    # KEYS[2] = packet_queue:{user_id}  (packet list)
    # ARGV[1..N-2] = packet bytes
    # ARGV[N-1] = max_size
    # ARGV[N] = ttl
    _ENQUEUE_SCRIPT: ClassVar[Script] = Script("""\
if redis.call('EXISTS', KEYS[1]) == 0 then
    return 0
end
for i = 1, #ARGV - 2 do
    redis.call('RPUSH', KEYS[2], ARGV[i])
end
local max_size = tonumber(ARGV[#ARGV - 1])
redis.call('LTRIM', KEYS[2], -max_size, -1)
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[#ARGV]))
return 1""")

    # Lua script: atomically refresh TTL on meta and queue keys.
    # KEYS[1] = pq_meta:{user_id}
    # KEYS[2] = packet_queue:{user_id}
    # ARGV[1] = ttl
    _REFRESH_SCRIPT: ClassVar[Script] = Script("""\
redis.call('SET', KEYS[1], '1', 'EX', tonumber(ARGV[1]))
if redis.call('EXISTS', KEYS[2]) == 1 then
    redis.call('EXPIRE', KEYS[2], tonumber(ARGV[1]))
end
return 1""")

    def __init__(
        self,
        client: GlideClient,
        *,
        max_size: int = 4096,
        ttl: int = 300,
        key_prefix: str = "",
    ) -> None:
        """Valkey client と packet queue の運用値を持つ instance を初期化する.

        Args:
            client (GlideClient): Lua script を実行する Valkey client.
            max_size (int): user ごとに保持する packet 数の上限.
            ttl (int): enqueue 時に queue key へ設定する TTL 秒数.
            key_prefix (str): key 名前空間を分離する任意の prefix.

        Returns:
            None: packet queue instance を初期化したことを表す.
        """
        self._client: GlideClient = client
        self._max_size: int = max_size
        self._ttl: int = ttl
        self._prefix: str = key_prefix

    # -- key helpers ----------------------------------------------------------

    def _queue_key(self, user_id: int) -> str:
        """User の packet List に対応する Valkey key を組み立てる.

        Args:
            user_id (int): key に埋め込む user id.

        Returns:
            str: `{prefix}packet_queue:{user_id}` 形式の packet List key.
        """
        return f"{self._prefix}packet_queue:{user_id}"

    def _meta_key(self, user_id: int) -> str:
        """User の session activation marker に対応する Valkey key を組み立てる.

        Args:
            user_id (int): key に埋め込む user id.

        Returns:
            str: `{prefix}pq_meta:{user_id}` 形式の activation marker key.
        """
        return f"{self._prefix}pq_meta:{user_id}"

    # -- PacketQueue Protocol methods -----------------------------------------

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        """構築済み S2C packet を active user の Valkey queue に追加する.

        Args:
            user_id (int): 追加先 queue を持つ user id.
            *data (bytes): 個別の S2C packet。複数指定時は同じ順序で追加する.

        Returns:
            None: enqueue script 実行の完了を表す.

        Notes:
            data が空なら script を呼ばない.
            activation marker がない user の packet は script が破棄し、size upper bound を超える
            packet は最も古いものから切り捨てる.
        """
        if not data:
            return
        args: list[TEncodable] = [*data, str(self._max_size), str(self._ttl)]
        _ = await self._client.invoke_script(
            self._ENQUEUE_SCRIPT,
            keys=[self._meta_key(user_id), self._queue_key(user_id)],
            args=args,
        )

    async def dequeue_all(self, user_id: int) -> bytes:
        """Valkey queue を atomic に drain し、packet を連結した bytes を返す.

        Args:
            user_id (int): drain 対象 queue の user id.

        Returns:
            bytes: queue 内 packet を連結した値。queue が空または未存在なら b"".

        Notes:
            dequeue script は List を読み出してから削除するため、同時 drain で packet を
            重複返却しない.
        """
        packets = await self._client.invoke_script(
            self._DEQUEUE_ALL_SCRIPT,
            keys=[self._queue_key(user_id)],
            args=[],
        )
        if not packets:
            return b""
        return b"".join(cast("list[bytes]", packets))

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """Queue を active session として有効化し、既存 key の TTL を更新する.

        Args:
            user_id (int): 更新する queue の user id.
            ttl (int): session と同期する有効期限の秒数.

        Returns:
            None: refresh script 実行の完了を表す.

        Notes:
            activation marker は常に設定し、packet List が存在する場合だけその TTL を更新する.
        """
        _ = await self._client.invoke_script(
            self._REFRESH_SCRIPT,
            keys=[self._meta_key(user_id), self._queue_key(user_id)],
            args=[str(ttl)],
        )
