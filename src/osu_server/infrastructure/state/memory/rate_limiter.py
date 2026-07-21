"""Timestamp list を使う rate limiter の in-memory 実装を提供する module."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class InMemoryRateLimiter:
    """User ごとの action timestamp を memory で保持する rate limiter.

    Attributes:
        _timestamps (dict[int, list[float]]): user id ごとの許可済み action timestamp.
        _time_func (Callable[[], float]): 現在時刻を秒で返す注入可能な clock.

    Notes:
        check は window 外の timestamp を削除してから判定する.
        thread-safe ではなく、single-threaded test environment 向けに限定する.
    """

    def __init__(self, *, time_func: Callable[[], float] | None = None) -> None:
        """Timestamp storage と action 判定用 clock を初期化する.

        Args:
            time_func (Callable[[], float] | None): 現在時刻を秒で返す clock。未指定時は time.time.

        Returns:
            None: rate limiter instance を初期化したことを表す.
        """
        self._timestamps: dict[int, list[float]] = {}
        self._time_func: Callable[[], float] = time_func or time.time

    async def check(self, user_id: int, limit: int, window: int) -> bool:
        """User の現在の action が time window 内で許可されるかを判定する.

        Args:
            user_id (int): 判定対象の user id.
            limit (int): window 内で許可する action の上限数.
            window (int): 判定 window の秒数.

        Returns:
            bool: action を許可して timestamp を記録した場合は True、上限到達なら False.

        Notes:
            上限到達時は action を記録せず、期限切れ timestamp だけを保存する.
        """
        now = self._time_func()
        cutoff = now - window

        timestamps = self._timestamps.get(user_id, [])
        # Prune expired entries
        timestamps = [t for t in timestamps if t > cutoff]

        if len(timestamps) >= limit:
            self._timestamps[user_id] = timestamps
            return False

        timestamps.append(now)
        self._timestamps[user_id] = timestamps
        return True
