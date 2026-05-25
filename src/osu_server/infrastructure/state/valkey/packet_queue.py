"""ValkeyPacketQueue — Valkey-backed S2C packet queue implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from glide import Script

if TYPE_CHECKING:
    from glide import GlideClient
    from glide_shared.constants import TEncodable


class ValkeyPacketQueue:
    """Valkey implementation of the PacketQueue Protocol.

    Key patterns:
        - ``{prefix}packet_queue:{user_id}`` -> List of S2C packet bytes
        - ``{prefix}pq_meta:{user_id}`` -> activation flag (session-active marker)

    Both keys share the same TTL.  ``refresh_ttl`` activates the queue by
    setting the meta key; ``enqueue`` checks its existence before pushing.

    Atomicity: ``enqueue`` and ``dequeue_all`` use Lua scripts
    (via Script objects / EVALSHA) to avoid TOCTOU races.
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
        self._client: GlideClient = client
        self._max_size: int = max_size
        self._ttl: int = ttl
        self._prefix: str = key_prefix

    # -- key helpers ----------------------------------------------------------

    def _queue_key(self, user_id: int) -> str:
        return f"{self._prefix}packet_queue:{user_id}"

    def _meta_key(self, user_id: int) -> str:
        return f"{self._prefix}pq_meta:{user_id}"

    # -- PacketQueue Protocol methods -----------------------------------------

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        """Append packets to the user's queue.  Discard if no active session."""
        if not data:
            return
        args: list[TEncodable] = [*data, str(self._max_size), str(self._ttl)]
        _ = await self._client.invoke_script(
            self._ENQUEUE_SCRIPT,
            keys=[self._meta_key(user_id), self._queue_key(user_id)],
            args=args,
        )

    async def dequeue_all(self, user_id: int) -> bytes:
        """Drain all packets and return concatenated bytes."""
        packets = await self._client.invoke_script(
            self._DEQUEUE_ALL_SCRIPT,
            keys=[self._queue_key(user_id)],
            args=[],
        )
        if not packets:
            return b""
        return b"".join(cast("list[bytes]", packets))

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """Activate the queue and refresh TTL on both meta and queue keys."""
        _ = await self._client.invoke_script(
            self._REFRESH_SCRIPT,
            keys=[self._meta_key(user_id), self._queue_key(user_id)],
            args=[str(ttl)],
        )
