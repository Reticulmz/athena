"""Tests for PacketQueue Protocol + InMemoryPacketQueue."""

from __future__ import annotations

import pytest

from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue


@pytest.fixture
def queue() -> InMemoryPacketQueue:
    return InMemoryPacketQueue(max_size=4096)


@pytest.fixture
def small_queue() -> InMemoryPacketQueue:
    return InMemoryPacketQueue(max_size=3)


async def test_enqueue_single_packet(queue: InMemoryPacketQueue) -> None:
    """enqueue stores a single packet; dequeue_all returns it."""
    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.enqueue(1, b"\x01\x02\x03")

    result = await queue.dequeue_all(user_id=1)

    assert result == b"\x01\x02\x03"


async def test_enqueue_multiple_packets_single_call(queue: InMemoryPacketQueue) -> None:
    """enqueue with multiple *data args stores all; dequeue_all returns concatenated."""
    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.enqueue(1, b"\x01", b"\x02", b"\x03")

    result = await queue.dequeue_all(user_id=1)

    assert result == b"\x01\x02\x03"


async def test_enqueue_multiple_calls(queue: InMemoryPacketQueue) -> None:
    """Multiple enqueue calls accumulate; dequeue_all returns all concatenated."""
    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.enqueue(1, b"\x01\x02")
    await queue.enqueue(1, b"\x03\x04")

    result = await queue.dequeue_all(user_id=1)

    assert result == b"\x01\x02\x03\x04"


async def test_dequeue_all_empties_queue(queue: InMemoryPacketQueue) -> None:
    """After dequeue_all, subsequent call returns empty bytes."""
    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.enqueue(1, b"\x01\x02")

    first = await queue.dequeue_all(user_id=1)
    second = await queue.dequeue_all(user_id=1)

    assert first == b"\x01\x02"
    assert second == b""


async def test_dequeue_empty_queue(queue: InMemoryPacketQueue) -> None:
    """dequeue_all on an active but empty queue returns b""."""
    await queue.refresh_ttl(user_id=1, ttl=300)

    result = await queue.dequeue_all(user_id=1)

    assert result == b""


async def test_dequeue_nonexistent_user(queue: InMemoryPacketQueue) -> None:
    """dequeue_all for unknown user returns b""."""
    result = await queue.dequeue_all(user_id=9999)

    assert result == b""


async def test_size_limit_trims_oldest(small_queue: InMemoryPacketQueue) -> None:
    """When queue exceeds max_size, oldest packets are trimmed."""
    await small_queue.refresh_ttl(user_id=1, ttl=300)
    for i in range(5):
        await small_queue.enqueue(1, bytes([i]))

    result = await small_queue.dequeue_all(user_id=1)

    assert result == b"\x02\x03\x04"


async def test_size_limit_trims_oldest_bulk(small_queue: InMemoryPacketQueue) -> None:
    """Bulk enqueue also respects max_size, trimming oldest."""
    await small_queue.refresh_ttl(user_id=1, ttl=300)
    await small_queue.enqueue(1, b"\x00", b"\x01", b"\x02", b"\x03", b"\x04")

    result = await small_queue.dequeue_all(user_id=1)

    assert result == b"\x02\x03\x04"


async def test_enqueue_without_session_discards(queue: InMemoryPacketQueue) -> None:
    """enqueue without prior refresh_ttl discards packets (session absent)."""
    await queue.enqueue(1, b"\x01\x02\x03")

    result = await queue.dequeue_all(user_id=1)

    assert result == b""


async def test_enqueue_empty_data_is_noop(queue: InMemoryPacketQueue) -> None:
    """enqueue with no data args is a no-op."""
    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.enqueue(1)

    result = await queue.dequeue_all(user_id=1)

    assert result == b""


async def test_independent_user_queues(queue: InMemoryPacketQueue) -> None:
    """Each user has an independent queue."""
    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.refresh_ttl(user_id=2, ttl=300)
    await queue.enqueue(1, b"\x01")
    await queue.enqueue(2, b"\x02")

    result1 = await queue.dequeue_all(user_id=1)
    result2 = await queue.dequeue_all(user_id=2)

    assert result1 == b"\x01"
    assert result2 == b"\x02"


async def test_refresh_ttl_activates_queue(queue: InMemoryPacketQueue) -> None:
    """refresh_ttl enables enqueue for a user."""
    await queue.enqueue(1, b"\x01")
    assert await queue.dequeue_all(user_id=1) == b""

    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.enqueue(1, b"\x02")
    assert await queue.dequeue_all(user_id=1) == b"\x02"
