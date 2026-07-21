"""User 単位の rate limit を判定する抽象 contract を定義する module."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RateLimiter(Protocol):
    """User ごとの action 回数を time window 内で制限する contract.

    Notes:
        check は現在の action を判定対象に含め、許可時だけその action を記録する.
    """

    async def check(self, user_id: int, limit: int, window: int) -> bool:
        """User が現在の action を実行できるかを判定する.

        Args:
            user_id (int): 判定対象の user id.
            limit (int): window 内で許可する action の上限数.
            window (int): 判定 window の秒数.

        Returns:
            bool: action を許可する場合は True、rate limited の場合は False.
        """
        ...
