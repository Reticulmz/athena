"""InMemoryRateLimiter — timestamp-list-based rate limiter for testing."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class InMemoryRateLimiter:
    """In-memory implementation of the RateLimiter Protocol.

    Uses a dict mapping user_id to a list of timestamps (floats).
    On each ``check`` call, expired timestamps outside the window are pruned,
    the current timestamp is appended, and the count is compared against the limit.

    Not thread-safe — intended for single-threaded test environments only.
    """

    def __init__(self, *, time_func: Callable[[], float] | None = None) -> None:
        self._timestamps: dict[int, list[float]] = {}
        self._time_func: Callable[[], float] = time_func or time.time

    async def check(self, user_id: int, limit: int, window: int) -> bool:
        """Check rate limit for the user.

        Returns True if allowed, False if rate limited.
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
