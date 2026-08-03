"""RateLimiterのmemory実装に対する時間窓契約を検証する."""

from __future__ import annotations

import pytest

from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter


@pytest.fixture
def limiter() -> InMemoryRateLimiter:
    """各testへ時刻共有のない空のrate limiterを提供する.

    Returns:
        InMemoryRateLimiter: 各testで独立して使用するrate limiter.
    """
    return InMemoryRateLimiter()


# -- Protocol conformance ----------------------------------------------------


def test_implements_protocol() -> None:
    """memory実装を生成したときRateLimiter Protocolとして認識されることを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
    assert isinstance(InMemoryRateLimiter(), RateLimiter)


# -- Allowed within limit ----------------------------------------------------


async def test_allowed_within_limit(limiter: InMemoryRateLimiter) -> None:
    """時間窓内で上限回数まで照会したとき全requestを許可することを確認する.

    Args:
        limiter (InMemoryRateLimiter): 検証対象の空のrate limiter.

    Returns:
        None: 検証を完了し値を返さない.
    """
    limit = 3
    window = 10

    assert await limiter.check(1, limit, window) is True
    assert await limiter.check(1, limit, window) is True
    assert await limiter.check(1, limit, window) is True


# -- Rejected when exceeded --------------------------------------------------


async def test_rejected_when_exceeded(limiter: InMemoryRateLimiter) -> None:
    """時間窓内で上限まで許可した後のrequestを拒否することを確認する.

    Args:
        limiter (InMemoryRateLimiter): 検証対象の空のrate limiter.

    Returns:
        None: 検証を完了し値を返さない.
    """
    limit = 3
    window = 10

    for _ in range(limit):
        _ = await limiter.check(1, limit, window)

    assert await limiter.check(1, limit, window) is False


async def test_rejected_stays_rejected(limiter: InMemoryRateLimiter) -> None:
    """上限超過後の同一時間窓では後続requestも連続して拒否することを確認する.

    Args:
        limiter (InMemoryRateLimiter): 検証対象の空のrate limiter.

    Returns:
        None: 検証を完了し値を返さない.
    """
    limit = 2
    window = 10

    _ = await limiter.check(1, limit, window)
    _ = await limiter.check(1, limit, window)

    assert await limiter.check(1, limit, window) is False
    assert await limiter.check(1, limit, window) is False


# -- Window reset ------------------------------------------------------------


async def test_window_reset_allows_again() -> None:
    """上限到達後に時間窓を越えたrequestを再び許可することを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
    limit = 2
    window = 5
    base_time = 1000.0

    call_count = 0

    def mock_time() -> float:
        """呼出回数に応じて窓内時刻または期限後時刻を返す.

        Returns:
            float: 呼出回数に対応する窓内または期限後のfake時刻.
        """
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
    """一方のuserが上限へ達しても別userのrequestを許可することを確認する.

    Args:
        limiter (InMemoryRateLimiter): 検証対象の空のrate limiter.

    Returns:
        None: 検証を完了し値を返さない.
    """
    limit = 1
    window = 10

    _ = await limiter.check(1, limit, window)
    assert await limiter.check(1, limit, window) is False

    # Different user should still be allowed
    assert await limiter.check(2, limit, window) is True


# -- Edge cases --------------------------------------------------------------


async def test_limit_of_one(limiter: InMemoryRateLimiter) -> None:
    """上限1では最初のrequestだけを許可し次を拒否することを確認する.

    Args:
        limiter (InMemoryRateLimiter): 検証対象の空のrate limiter.

    Returns:
        None: 検証を完了し値を返さない.
    """
    assert await limiter.check(1, 1, 10) is True
    assert await limiter.check(1, 1, 10) is False
