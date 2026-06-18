"""Integration tests for ValkeyPacketQueue against a real Valkey instance.

Runs the same test matrix as InMemoryPacketQueue unit tests (Protocol
compliance) plus Valkey-specific tests for atomicity, TTL, and concurrency.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from glide import GlideClient
    from glide_shared.constants import TEncodable

from osu_server.infrastructure.cache.valkey_client import create_valkey_client
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.valkey.packet_queue import ValkeyPacketQueue
from tests.support.service_availability import require_tcp_service_url

_KEY_PREFIX = "athena_test:"


def _get_valkey_url() -> str:
    return require_tcp_service_url("VALKEY_URL", default_port=6379)


@pytest.fixture
async def valkey_client() -> AsyncGenerator[GlideClient]:
    client = await create_valkey_client(_get_valkey_url())
    yield client
    await client.close()


@pytest.fixture
async def valkey_key_prefix(valkey_client: GlideClient) -> AsyncGenerator[str]:
    key_prefix = f"{_KEY_PREFIX}packet_queue:{uuid4().hex}:"
    yield key_prefix
    for pattern in (f"{key_prefix}packet_queue:*", f"{key_prefix}pq_meta:*"):
        cursor: str = "0"
        while True:
            next_cursor, keys = await valkey_client.scan(cursor, match=pattern, count=100)
            if keys:
                _ = await valkey_client.delete(cast("list[TEncodable]", keys))
            cursor = next_cursor.decode() if isinstance(next_cursor, bytes) else str(next_cursor)
            if cursor == "0":
                break


@pytest.fixture
def valkey_queue(valkey_client: GlideClient, valkey_key_prefix: str) -> ValkeyPacketQueue:
    return ValkeyPacketQueue(valkey_client, max_size=4096, ttl=300, key_prefix=valkey_key_prefix)


@pytest.fixture
def memory_queue() -> InMemoryPacketQueue:
    return InMemoryPacketQueue(max_size=4096)


@pytest.fixture(params=["valkey", "memory"])
def queue(request: pytest.FixtureRequest) -> PacketQueue:
    param = cast("str", request.param)
    if param == "valkey":
        return cast("PacketQueue", request.getfixturevalue("valkey_queue"))
    return cast("PacketQueue", request.getfixturevalue("memory_queue"))


@pytest.fixture
def valkey_small_queue(valkey_client: GlideClient, valkey_key_prefix: str) -> ValkeyPacketQueue:
    return ValkeyPacketQueue(valkey_client, max_size=3, ttl=300, key_prefix=valkey_key_prefix)


@pytest.fixture
def memory_small_queue() -> InMemoryPacketQueue:
    return InMemoryPacketQueue(max_size=3)


@pytest.fixture(params=["valkey", "memory"])
def small_queue(request: pytest.FixtureRequest) -> PacketQueue:
    param = cast("str", request.param)
    if param == "valkey":
        return cast("PacketQueue", request.getfixturevalue("valkey_small_queue"))
    return cast("PacketQueue", request.getfixturevalue("memory_small_queue"))


# ---------------------------------------------------------------------------
# Protocol compliance — both implementations through same test matrix
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    """ValkeyPacketQueue satisfies the PacketQueue Protocol."""

    def test_valkey_packet_queue_is_packet_queue(
        self,
        valkey_queue: ValkeyPacketQueue,
    ) -> None:
        assert isinstance(valkey_queue, PacketQueue)


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
# Valkey-specific tests — atomicity, TTL, concurrency
# ---------------------------------------------------------------------------


class TestValkeyTTLExpiry:
    """Valkey TTL causes automatic queue cleanup."""

    async def test_ttl_expiry_cleans_up_queue(
        self,
        valkey_client: GlideClient,
        valkey_key_prefix: str,
    ) -> None:
        queue = ValkeyPacketQueue(
            valkey_client,
            max_size=4096,
            ttl=1,
            key_prefix=valkey_key_prefix,
        )
        await queue.refresh_ttl(user_id=1, ttl=1)
        await queue.enqueue(1, b"\x01\x02\x03")

        await asyncio.sleep(1.5)

        result = await queue.dequeue_all(user_id=1)
        assert result == b""

    async def test_refresh_ttl_extends_expiry(
        self,
        valkey_client: GlideClient,
        valkey_key_prefix: str,
    ) -> None:
        queue = ValkeyPacketQueue(
            valkey_client,
            max_size=4096,
            ttl=2,
            key_prefix=valkey_key_prefix,
        )
        await queue.refresh_ttl(user_id=1, ttl=2)
        await queue.enqueue(1, b"\x01")

        queue_key = f"{valkey_key_prefix}packet_queue:1"
        ttl_before_refresh = await valkey_client.ttl(queue_key)
        await queue.refresh_ttl(user_id=1, ttl=5)
        ttl_after_refresh = await valkey_client.ttl(queue_key)

        result = await queue.dequeue_all(user_id=1)
        assert ttl_before_refresh > 0
        assert ttl_after_refresh > ttl_before_refresh
        assert result == b"\x01"


class TestValkeyConcurrentDrain:
    """Concurrent dequeue_all does not produce duplicates."""

    async def test_concurrent_drain_no_duplicates(self, valkey_queue: ValkeyPacketQueue) -> None:
        packet_count = 100
        await valkey_queue.refresh_ttl(user_id=1, ttl=300)
        for i in range(packet_count):
            await valkey_queue.enqueue(1, bytes([i % 256]))

        results = await asyncio.gather(
            valkey_queue.dequeue_all(user_id=1),
            valkey_queue.dequeue_all(user_id=1),
            valkey_queue.dequeue_all(user_id=1),
        )

        non_empty = [r for r in results if r != b""]
        assert len(non_empty) == 1
        assert len(non_empty[0]) == packet_count
