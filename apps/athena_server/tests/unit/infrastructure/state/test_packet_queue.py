"""PacketQueueのmemory実装に対するFIFO契約を検証する."""

from __future__ import annotations

import pytest

from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue


@pytest.fixture
def queue() -> InMemoryPacketQueue:
    """通常上限を持つ空のpacket queueを各testへ提供する.

    Returns:
        InMemoryPacketQueue: 各testで独立して使用するpacket queue.
    """
    return InMemoryPacketQueue(max_size=4096)


@pytest.fixture
def small_queue() -> InMemoryPacketQueue:
    """trimming挙動を検証するため上限3の空queueを提供する.

    Returns:
        InMemoryPacketQueue: 各testで独立して使用するpacket queue.
    """
    return InMemoryPacketQueue(max_size=3)


async def test_enqueue_single_packet(queue: InMemoryPacketQueue) -> None:
    """有効sessionへ1packetをenqueueしたときdequeue_allが同じbytesを返すことを確認する.

    Args:
        queue (InMemoryPacketQueue): 検証対象のpacket queue.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.enqueue(1, b"\x01\x02\x03")

    result = await queue.dequeue_all(user_id=1)

    assert result == b"\x01\x02\x03"


async def test_enqueue_multiple_packets_single_call(queue: InMemoryPacketQueue) -> None:
    """1回の複数packet enqueue後にdequeue_allが入力順の連結bytesを返すことを確認する.

    Args:
        queue (InMemoryPacketQueue): 検証対象のpacket queue.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.enqueue(1, b"\x01", b"\x02", b"\x03")

    result = await queue.dequeue_all(user_id=1)

    assert result == b"\x01\x02\x03"


async def test_enqueue_multiple_calls(queue: InMemoryPacketQueue) -> None:
    """複数回enqueueしたときdequeue_allが全packetを順序どおり連結して返すことを確認する.

    Args:
        queue (InMemoryPacketQueue): 検証対象のpacket queue.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.enqueue(1, b"\x01\x02")
    await queue.enqueue(1, b"\x03\x04")

    result = await queue.dequeue_all(user_id=1)

    assert result == b"\x01\x02\x03\x04"


async def test_dequeue_all_empties_queue(queue: InMemoryPacketQueue) -> None:
    """dequeue_allでpacketを取得した後は次の取得が空bytesを返すことを確認する.

    Args:
        queue (InMemoryPacketQueue): 検証対象のpacket queue.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.enqueue(1, b"\x01\x02")

    first = await queue.dequeue_all(user_id=1)
    second = await queue.dequeue_all(user_id=1)

    assert first == b"\x01\x02"
    assert second == b""


async def test_dequeue_empty_queue(queue: InMemoryPacketQueue) -> None:
    """有効だがpacket未投入のqueueを取得したとき空bytesを返すことを確認する.

    Args:
        queue (InMemoryPacketQueue): 検証対象のpacket queue.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await queue.refresh_ttl(user_id=1, ttl=300)

    result = await queue.dequeue_all(user_id=1)

    assert result == b""


async def test_dequeue_nonexistent_user(queue: InMemoryPacketQueue) -> None:
    """未知userのqueueを取得したとき空bytesを返すことを確認する.

    Args:
        queue (InMemoryPacketQueue): 検証対象のpacket queue.

    Returns:
        None: 検証を完了し値を返さない.
    """
    result = await queue.dequeue_all(user_id=9999)

    assert result == b""


async def test_size_limit_trims_oldest(small_queue: InMemoryPacketQueue) -> None:
    """上限3のqueueへ5packetを投入したとき最古2件を除いた3packetを返すことを確認する.

    Args:
        small_queue (InMemoryPacketQueue): 検証対象のpacket queue.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await small_queue.refresh_ttl(user_id=1, ttl=300)
    for i in range(5):
        await small_queue.enqueue(1, bytes([i]))

    result = await small_queue.dequeue_all(user_id=1)

    assert result == b"\x02\x03\x04"


async def test_size_limit_trims_oldest_bulk(small_queue: InMemoryPacketQueue) -> None:
    """複数packetを一括投入して上限を超えたとき最古packetをtrimすることを確認する.

    Args:
        small_queue (InMemoryPacketQueue): 検証対象のpacket queue.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await small_queue.refresh_ttl(user_id=1, ttl=300)
    await small_queue.enqueue(1, b"\x00", b"\x01", b"\x02", b"\x03", b"\x04")

    result = await small_queue.dequeue_all(user_id=1)

    assert result == b"\x02\x03\x04"


async def test_enqueue_without_session_discards(queue: InMemoryPacketQueue) -> None:
    """sessionを有効化せずenqueueしたときpacketを保持せず空bytesを返すことを確認する.

    Args:
        queue (InMemoryPacketQueue): 検証対象のpacket queue.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await queue.enqueue(1, b"\x01\x02\x03")

    result = await queue.dequeue_all(user_id=1)

    assert result == b""


async def test_enqueue_empty_data_is_noop(queue: InMemoryPacketQueue) -> None:
    """dataなしでenqueueしたときqueue内容を変更せず空bytesを返すことを確認する.

    Args:
        queue (InMemoryPacketQueue): 検証対象のpacket queue.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.enqueue(1)

    result = await queue.dequeue_all(user_id=1)

    assert result == b""


async def test_independent_user_queues(queue: InMemoryPacketQueue) -> None:
    """2userへ別packetを投入したとき各dequeue_allが自身のpacketだけを返すことを確認する.

    Args:
        queue (InMemoryPacketQueue): 検証対象のpacket queue.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.refresh_ttl(user_id=2, ttl=300)
    await queue.enqueue(1, b"\x01")
    await queue.enqueue(2, b"\x02")

    result1 = await queue.dequeue_all(user_id=1)
    result2 = await queue.dequeue_all(user_id=2)

    assert result1 == b"\x01"
    assert result2 == b"\x02"


async def test_refresh_ttl_activates_queue(queue: InMemoryPacketQueue) -> None:
    """refresh_ttl前後でenqueue可否が変わり有効化後のpacketだけを返すことを確認する.

    Args:
        queue (InMemoryPacketQueue): 検証対象のpacket queue.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await queue.enqueue(1, b"\x01")
    assert await queue.dequeue_all(user_id=1) == b""

    await queue.refresh_ttl(user_id=1, ttl=300)
    await queue.enqueue(1, b"\x02")
    assert await queue.dequeue_all(user_id=1) == b"\x02"
