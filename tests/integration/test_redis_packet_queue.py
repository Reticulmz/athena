# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Integration tests for RedisPacketQueue against a real Redis instance.

Runs the same test matrix as InMemoryPacketQueue unit tests (Protocol
compliance) plus Redis-specific tests for atomicity, TTL, and concurrency.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from redis.asyncio import Redis

from osu_server.infrastructure.cache.redis_client import create_redis_client
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.redis.packet_queue import RedisPacketQueue

_KEY_PREFIX = "athena_test:"


def _get_redis_url() -> str:
    url = os.environ.get("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL not set")
    return url


@pytest.fixture
async def redis_client() -> AsyncGenerator[Redis]:
    client = create_redis_client(_get_redis_url())
    yield client
    for pattern in (f"{_KEY_PREFIX}packet_queue:*", f"{_KEY_PREFIX}pq_meta:*"):
        keys = await client.keys(pattern)
        if keys:
            await client.delete(*keys)
    await client.aclose()


@pytest.fixture
def redis_queue(redis_client: Redis) -> RedisPacketQueue:
    return RedisPacketQueue(redis_client, max_size=4096, ttl=300, key_prefix=_KEY_PREFIX)


@pytest.fixture
def memory_queue() -> InMemoryPacketQueue:
    return InMemoryPacketQueue(max_size=4096)


@pytest.fixture(params=["redis", "memory"])
def queue(
    request: pytest.FixtureRequest,
    redis_queue: RedisPacketQueue,
    memory_queue: InMemoryPacketQueue,
) -> PacketQueue:
    if request.param == "redis":
        return redis_queue
    return memory_queue


@pytest.fixture
def redis_small_queue(redis_client: Redis) -> RedisPacketQueue:
    return RedisPacketQueue(redis_client, max_size=3, ttl=300, key_prefix=_KEY_PREFIX)


@pytest.fixture
def memory_small_queue() -> InMemoryPacketQueue:
    return InMemoryPacketQueue(max_size=3)


@pytest.fixture(params=["redis", "memory"])
def small_queue(
    request: pytest.FixtureRequest,
    redis_small_queue: RedisPacketQueue,
    memory_small_queue: InMemoryPacketQueue,
) -> PacketQueue:
    if request.param == "redis":
        return redis_small_queue
    return memory_small_queue


# ---------------------------------------------------------------------------
# Protocol compliance — both implementations through same test matrix
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    """RedisPacketQueue satisfies the PacketQueue Protocol."""

    def test_redis_packet_queue_is_packet_queue(
        self,
        redis_queue: RedisPacketQueue,
    ) -> None:
        assert isinstance(redis_queue, PacketQueue)


class TestEnqueue:
    """enqueue stores packets; dequeue_all returns them concatenated."""

    async def test_enqueue_single_packet(self, queue: PacketQueue) -> None:
        await queue.refresh_ttl(user_id=1, ttl=300)
        await queue.enqueue(1, b"\x01\x02\x03")

        result = await queue.dequeue_all(user_id=1)

        assert result == b"\x01\x02\x03"

    async def test_enqueue_multiple_packets_single_call(self, queue: PacketQueue) -> None:
        await queue.refresh_ttl(user_id=1, ttl=300)
        await queue.enqueue(1, b"\x01", b"\x02", b"\x03")

        result = await queue.dequeue_all(user_id=1)

        assert result == b"\x01\x02\x03"

    async def test_enqueue_multiple_calls(self, queue: PacketQueue) -> None:
        await queue.refresh_ttl(user_id=1, ttl=300)
        await queue.enqueue(1, b"\x01\x02")
        await queue.enqueue(1, b"\x03\x04")

        result = await queue.dequeue_all(user_id=1)

        assert result == b"\x01\x02\x03\x04"

    async def test_enqueue_empty_data_is_noop(self, queue: PacketQueue) -> None:
        await queue.refresh_ttl(user_id=1, ttl=300)
        await queue.enqueue(1)

        result = await queue.dequeue_all(user_id=1)

        assert result == b""

    async def test_enqueue_without_session_discards(self, queue: PacketQueue) -> None:
        await queue.enqueue(1, b"\x01\x02\x03")

        result = await queue.dequeue_all(user_id=1)

        assert result == b""


class TestDequeueAll:
    """dequeue_all drains the queue and returns concatenated bytes."""

    async def test_dequeue_all_empties_queue(self, queue: PacketQueue) -> None:
        await queue.refresh_ttl(user_id=1, ttl=300)
        await queue.enqueue(1, b"\x01\x02")

        first = await queue.dequeue_all(user_id=1)
        second = await queue.dequeue_all(user_id=1)

        assert first == b"\x01\x02"
        assert second == b""

    async def test_dequeue_empty_queue(self, queue: PacketQueue) -> None:
        await queue.refresh_ttl(user_id=1, ttl=300)

        result = await queue.dequeue_all(user_id=1)

        assert result == b""

    async def test_dequeue_nonexistent_user(self, queue: PacketQueue) -> None:
        result = await queue.dequeue_all(user_id=9999)

        assert result == b""


class TestSizeLimit:
    """Queue respects max_size, trimming oldest packets."""

    async def test_size_limit_trims_oldest(self, small_queue: PacketQueue) -> None:
        await small_queue.refresh_ttl(user_id=1, ttl=300)
        for i in range(5):
            await small_queue.enqueue(1, bytes([i]))

        result = await small_queue.dequeue_all(user_id=1)

        assert result == b"\x02\x03\x04"

    async def test_size_limit_trims_oldest_bulk(self, small_queue: PacketQueue) -> None:
        await small_queue.refresh_ttl(user_id=1, ttl=300)
        await small_queue.enqueue(1, b"\x00", b"\x01", b"\x02", b"\x03", b"\x04")

        result = await small_queue.dequeue_all(user_id=1)

        assert result == b"\x02\x03\x04"


class TestIndependentQueues:
    """Each user has an independent queue."""

    async def test_independent_user_queues(self, queue: PacketQueue) -> None:
        await queue.refresh_ttl(user_id=1, ttl=300)
        await queue.refresh_ttl(user_id=2, ttl=300)
        await queue.enqueue(1, b"\x01")
        await queue.enqueue(2, b"\x02")

        result1 = await queue.dequeue_all(user_id=1)
        result2 = await queue.dequeue_all(user_id=2)

        assert result1 == b"\x01"
        assert result2 == b"\x02"


class TestRefreshTTL:
    """refresh_ttl activates the queue for enqueue."""

    async def test_refresh_ttl_activates_queue(self, queue: PacketQueue) -> None:
        await queue.enqueue(1, b"\x01")
        assert await queue.dequeue_all(user_id=1) == b""

        await queue.refresh_ttl(user_id=1, ttl=300)
        await queue.enqueue(1, b"\x02")
        assert await queue.dequeue_all(user_id=1) == b"\x02"


# ---------------------------------------------------------------------------
# Redis-specific tests — atomicity, TTL, concurrency
# ---------------------------------------------------------------------------


class TestRedisTTLExpiry:
    """Redis TTL causes automatic queue cleanup."""

    async def test_ttl_expiry_cleans_up_queue(self, redis_client: Redis) -> None:
        queue = RedisPacketQueue(redis_client, max_size=4096, ttl=1, key_prefix=_KEY_PREFIX)
        await queue.refresh_ttl(user_id=1, ttl=1)
        await queue.enqueue(1, b"\x01\x02\x03")

        await asyncio.sleep(1.5)

        result = await queue.dequeue_all(user_id=1)
        assert result == b""

    async def test_refresh_ttl_extends_expiry(self, redis_client: Redis) -> None:
        queue = RedisPacketQueue(redis_client, max_size=4096, ttl=2, key_prefix=_KEY_PREFIX)
        await queue.refresh_ttl(user_id=1, ttl=2)
        await queue.enqueue(1, b"\x01")

        await asyncio.sleep(1.0)
        await queue.refresh_ttl(user_id=1, ttl=2)

        await asyncio.sleep(1.5)

        result = await queue.dequeue_all(user_id=1)
        assert result == b"\x01"


class TestRedisConcurrentDrain:
    """Concurrent dequeue_all does not produce duplicates."""

    async def test_concurrent_drain_no_duplicates(self, redis_queue: RedisPacketQueue) -> None:
        packet_count = 100
        await redis_queue.refresh_ttl(user_id=1, ttl=300)
        for i in range(packet_count):
            await redis_queue.enqueue(1, bytes([i % 256]))

        results = await asyncio.gather(
            redis_queue.dequeue_all(user_id=1),
            redis_queue.dequeue_all(user_id=1),
            redis_queue.dequeue_all(user_id=1),
        )

        non_empty = [r for r in results if r != b""]
        assert len(non_empty) == 1
        assert len(non_empty[0]) == packet_count
