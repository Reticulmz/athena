"""PacketQueue Protocol — abstract interface for S2C packet queue management."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PacketQueue(Protocol):
    """Protocol for per-user S2C packet queue operations.

    Implementations must support enqueue, dequeue_all, and refresh_ttl.
    """

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        """S2C パケット(ビルド済み bytes)をキューに追加する。

        各引数が独立した1パケット。複数指定時は一括投入される。
        セッションが存在しない場合、パケットは破棄される。
        キューがサイズ上限を超えた場合、最も古いパケットから切り捨てる。
        """
        ...

    async def dequeue_all(self, user_id: int) -> bytes:
        """全パケットを drain し、連結した bytes を返す。キューは空になる。

        キューが空の場合は b"" を返す。
        """
        ...

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """キューの TTL をリフレッシュする。セッション TTL と連動して呼び出す。"""
        ...
