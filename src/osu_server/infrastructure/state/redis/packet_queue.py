# pyright: reportAny=false
"""RedisPacketQueue — Redis-backed S2C packet queue implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisPacketQueue:
    """Redis implementation of the PacketQueue Protocol.

    Key patterns:
        - ``{prefix}packet_queue:{user_id}`` → List of S2C packet bytes
        - ``{prefix}pq_meta:{user_id}`` → activation flag (session-active marker)

    Both keys share the same TTL.  ``refresh_ttl`` activates the queue by
    setting the meta key; ``enqueue`` checks its existence before pushing.

    Atomicity: ``enqueue`` and ``dequeue_all`` use Lua scripts to avoid
    TOCTOU races.
    """

    # Lua script: atomically drain all packets from the queue.
    # KEYS[1] = packet_queue:{user_id}
    # Returns: list of packet bytes (empty list if queue is empty)
    _DEQUEUE_ALL_SCRIPT: Final[str] = """\
local packets = redis.call('LRANGE', KEYS[1], 0, -1)
if #packets > 0 then
    redis.call('DEL', KEYS[1])
end
return packets"""

    # Lua script: atomically enqueue packets with size limit and TTL.
    # KEYS[1] = pq_meta:{user_id}  (activation flag)
    # KEYS[2] = packet_queue:{user_id}  (packet list)
    # ARGV[1..N-2] = packet bytes
    # ARGV[N-1] = max_size
    # ARGV[N] = ttl
    _ENQUEUE_SCRIPT: Final[str] = """\
if redis.call('EXISTS', KEYS[1]) == 0 then
    return 0
end
for i = 1, #ARGV - 2 do
    redis.call('RPUSH', KEYS[2], ARGV[i])
end
local max_size = tonumber(ARGV[#ARGV - 1])
redis.call('LTRIM', KEYS[2], -max_size, -1)
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[#ARGV]))
return 1"""

    # Lua script: atomically refresh TTL on meta and queue keys.
    # KEYS[1] = pq_meta:{user_id}
    # KEYS[2] = packet_queue:{user_id}
    # ARGV[1] = ttl
    _REFRESH_SCRIPT: Final[str] = """\
redis.call('SET', KEYS[1], '1', 'EX', tonumber(ARGV[1]))
if redis.call('EXISTS', KEYS[2]) == 1 then
    redis.call('EXPIRE', KEYS[2], tonumber(ARGV[1]))
end
return 1"""

    def __init__(
        self,
        redis: Redis,
        *,
        max_size: int = 4096,
        ttl: int = 300,
        key_prefix: str = "",
    ) -> None:
        self._redis: Redis = redis
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
        _ = await self._redis.eval(  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
            self._ENQUEUE_SCRIPT,
            2,
            self._meta_key(user_id),
            self._queue_key(user_id),
            *data,  # pyright: ignore[reportArgumentType]
            str(self._max_size),
            str(self._ttl),
        )

    async def dequeue_all(self, user_id: int) -> bytes:
        """Drain all packets and return concatenated bytes."""
        packets = await self._redis.eval(  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
            self._DEQUEUE_ALL_SCRIPT,
            1,
            self._queue_key(user_id),
        )
        if not packets:
            return b""
        return b"".join(packets)  # pyright: ignore[reportArgumentType]

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """Activate the queue and refresh TTL on both meta and queue keys."""
        _ = await self._redis.eval(  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
            self._REFRESH_SCRIPT,
            2,
            self._meta_key(user_id),
            self._queue_key(user_id),
            str(ttl),
        )
