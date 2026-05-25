"""Tests for RateLimiter Protocol + InMemoryRateLimiter."""

from __future__ import annotations

import pytest

from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter


@pytest.fixture
def limiter() -> InMemoryRateLimiter:
    return InMemoryRateLimiter()


# -- Protocol conformance ----------------------------------------------------


def test_implements_protocol() -> None:
    """InMemoryRateLimiter satisfies the RateLimiter Protocol."""
    assert isinstance(InMemoryRateLimiter(), RateLimiter)


# -- Allowed within limit ----------------------------------------------------


async def test_allowed_within_limit(limiter: InMemoryRateLimiter) -> None:
    """Requests within the limit are allowed."""
    limit = 3
    window = 10

    assert await limiter.check(1, limit, window) is True
    assert await limiter.check(1, limit, window) is True
    assert await limiter.check(1, limit, window) is True


# -- Rejected when exceeded --------------------------------------------------


async def test_rejected_when_exceeded(limiter: InMemoryRateLimiter) -> None:
    """The request exceeding the limit is rejected."""
    limit = 3
    window = 10

    for _ in range(limit):
        _ = await limiter.check(1, limit, window)

    assert await limiter.check(1, limit, window) is False


async def test_rejected_stays_rejected(limiter: InMemoryRateLimiter) -> None:
    """Subsequent requests after exceeding the limit remain rejected."""
    limit = 2
    window = 10

    _ = await limiter.check(1, limit, window)
    _ = await limiter.check(1, limit, window)

    assert await limiter.check(1, limit, window) is False
    assert await limiter.check(1, limit, window) is False


# -- Window reset ------------------------------------------------------------


async def test_window_reset_allows_again() -> None:
    """After the window expires, requests are allowed again."""
    limit = 2
    window = 5
    base_time = 1000.0

    call_count = 0

    def mock_time() -> float:
        nonlocal call_count
        call_count += 1
        # First two calls: within window (time = 1000.0)
        if call_count <= limit:
            return base_time
        # Third call: after window expires (time = 1006.0)
        return base_time + window + 1

    limiter = InMemoryRateLimiter(time_func=mock_time)

    # Exhaust the limit
    _ = await limiter.check(1, limit, window)
    _ = await limiter.check(1, limit, window)

    # After window passes, should be allowed again
    assert await limiter.check(1, limit, window) is True


# -- User isolation ----------------------------------------------------------


async def test_users_are_independent(limiter: InMemoryRateLimiter) -> None:
    """Rate limits are tracked independently per user."""
    limit = 1
    window = 10

    _ = await limiter.check(1, limit, window)
    assert await limiter.check(1, limit, window) is False

    # Different user should still be allowed
    assert await limiter.check(2, limit, window) is True


# -- Edge cases --------------------------------------------------------------


async def test_limit_of_one(limiter: InMemoryRateLimiter) -> None:
    """A limit of 1 allows exactly one request."""
    assert await limiter.check(1, 1, 10) is True
    assert await limiter.check(1, 1, 10) is False
