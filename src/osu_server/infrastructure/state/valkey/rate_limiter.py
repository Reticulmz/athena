"""INCR と EXPIRE を使う rate limiter の Valkey 実装を提供する module."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from glide import GlideClient


class ValkeyRateLimiter:
    """User ごとの action count を Valkey String counter で管理する rate limiter.

    Attributes:
        _client (GlideClient): counter と TTL を操作する Valkey client.
        _prefix (str): 環境または test を分離する key prefix.

    Notes:
        counter key は `{prefix}rate_limit:user:{user_id}` を使用する.
        最初の INCR が 1 の場合だけ EXPIRE を設定し,count が limit を超えたら拒否する.
    """

    def __init__(self, client: GlideClient, *, key_prefix: str = "") -> None:
        """Valkey client と key prefix を持つ rate limiter を初期化する.

        Args:
            client (GlideClient): INCR と EXPIRE を実行する Valkey client.
            key_prefix (str): key 名前空間を分離する任意の prefix.
        """
        self._client: GlideClient = client
        self._prefix: str = key_prefix

    # -- key helpers ----------------------------------------------------------

    def _rate_key(self, user_id: int) -> str:
        """User の rate limit counter に対応する Valkey key を組み立てる.

        Args:
            user_id (int): key に埋め込む user id.

        Returns:
            str: `{prefix}rate_limit:user:{user_id}` 形式の counter key.
        """
        return f"{self._prefix}rate_limit:user:{user_id}"

    # -- RateLimiter Protocol methods -----------------------------------------

    async def check(self, user_id: int, limit: int, window: int) -> bool:
        """User の現在の action が rate limit 内かを Valkey counter で判定する.

        Args:
            user_id (int): 判定対象の user id.
            limit (int): window 内で許可する action の上限数.
            window (int): 最初の hit で設定する TTL 秒数.

        Returns:
            bool: increment 後の count が limit 以下なら True,超過なら False.

        Notes:
            counter が新規作成された場合だけ TTL を設定し,後続 hit は既存 TTL を延長しない.
        """
        key = self._rate_key(user_id)
        count: int = await self._client.incr(key)

        if count == 1:
            _ = await self._client.expire(key, window)

        return count <= limit
