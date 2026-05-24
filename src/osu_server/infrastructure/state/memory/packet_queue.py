"""InMemoryPacketQueue — dict-based packet queue for testing."""

from __future__ import annotations


class InMemoryPacketQueue:
    """In-memory implementation of the PacketQueue Protocol.

    Uses a plain dict keyed by user_id.  Queue activation requires
    a prior ``refresh_ttl`` call — enqueue to an unactivated user
    silently discards packets (simulates session-absent discard).

    Not thread-safe — intended for single-threaded test environments only.
    """

    def __init__(self, max_size: int = 4096) -> None:
        self._queues: dict[int, list[bytes]] = {}
        self._max_size: int = max_size

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        """Append packets to the user's queue.  Discard if no active session."""
        if not data:
            return
        queue = self._queues.get(user_id)
        if queue is None:
            return
        queue.extend(data)
        if len(queue) > self._max_size:
            del queue[: len(queue) - self._max_size]

    async def dequeue_all(self, user_id: int) -> bytes:
        """Drain all packets and return concatenated bytes."""
        queue = self._queues.get(user_id)
        if not queue:
            return b""
        result = b"".join(queue)
        queue.clear()
        return result

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
        """Activate the queue for a user.  TTL is ignored in memory."""
        if user_id not in self._queues:
            self._queues[user_id] = []
