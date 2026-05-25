"""RateLimiter Protocol — abstract interface for user-level rate limit checks."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RateLimiter(Protocol):
    """Protocol for per-user rate limiting.

    Implementations must support check.

    Methods: check.
    """

    async def check(self, user_id: int, limit: int, window: int) -> bool:
        """Determine whether the user is allowed to perform an action.

        Increments the counter for the user and checks against the limit
        within the given time window.

        Args:
            user_id: The user to check.
            limit: Maximum number of allowed actions within the window.
            window: Time window in seconds.

        Returns:
            True if the action is allowed, False if rate limited.
        """
        ...
