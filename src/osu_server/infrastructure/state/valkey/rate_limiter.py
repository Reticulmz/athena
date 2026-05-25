"""ValkeyRateLimiter — Valkey-backed rate limiter using INCR + EXPIRE."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from glide import GlideClient


class ValkeyRateLimiter:
    """Valkey implementation of the RateLimiter Protocol.

    Key pattern:
        - ``{prefix}rate_limit:user:{user_id}`` -> counter (String)

    Algorithm: INCR the key; if the result is 1 (first hit in window) set
    EXPIRE to ``window`` seconds.  If the counter exceeds ``limit``, return
    False (rate limited).
    """

    def __init__(self, client: GlideClient, *, key_prefix: str = "") -> None:
        self._client: GlideClient = client
        self._prefix: str = key_prefix

    # -- key helpers ----------------------------------------------------------

    def _rate_key(self, user_id: int) -> str:
        return f"{self._prefix}rate_limit:user:{user_id}"

    # -- RateLimiter Protocol methods -----------------------------------------

    async def check(self, user_id: int, limit: int, window: int) -> bool:
        """Check rate limit for the user.

        Returns True if allowed, False if rate limited.
        """
        key = self._rate_key(user_id)
        count: int = await self._client.incr(key)

        if count == 1:
            _ = await self._client.expire(key, window)

        return count <= limit
