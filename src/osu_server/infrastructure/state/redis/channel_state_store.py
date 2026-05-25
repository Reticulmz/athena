# pyright: reportAny=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportGeneralTypeIssues=false
# pyright: reportMissingTypeArgument=false
# pyright: reportArgumentType=false
"""RedisChannelStateStore — Redis-backed channel membership store."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisChannelStateStore:
    """Redis implementation of the ChannelStateStore Protocol.

    Key patterns:
        - ``{prefix}channel:{name}:members`` -> Set of user_id
        - ``{prefix}user:{user_id}:channels`` -> Set of channel_name

    Bidirectional indices are updated atomically via MULTI/EXEC pipelines.
    No TTL — membership is managed explicitly via add/remove/remove_user_from_all.
    """

    def __init__(self, redis: Redis, *, key_prefix: str = "") -> None:
        self._redis: Redis = redis
        self._prefix: str = key_prefix

    # -- key helpers ----------------------------------------------------------

    def _channel_key(self, channel_name: str) -> str:
        return f"{self._prefix}channel:{channel_name}:members"

    def _user_key(self, user_id: int) -> str:
        return f"{self._prefix}user:{user_id}:channels"

    # -- ChannelStateStore Protocol methods -----------------------------------

    async def add_member(self, channel_name: str, user_id: int) -> None:
        """Add a user to a channel.  Both Sets updated atomically."""
        async with self._redis.pipeline(transaction=True) as pipe:
            _ = pipe.sadd(self._channel_key(channel_name), user_id)
            _ = pipe.sadd(self._user_key(user_id), channel_name)
            _ = await pipe.execute()

    async def remove_member(self, channel_name: str, user_id: int) -> None:
        """Remove a user from a channel.  Both Sets updated atomically."""
        async with self._redis.pipeline(transaction=True) as pipe:
            _ = pipe.srem(self._channel_key(channel_name), user_id)
            _ = pipe.srem(self._user_key(user_id), channel_name)
            _ = await pipe.execute()

    async def is_member(self, channel_name: str, user_id: int) -> bool:
        """Return True if the user is a member of the channel."""
        result = await self._redis.sismember(self._channel_key(channel_name), user_id)
        return bool(result)

    async def get_members(self, channel_name: str) -> set[int]:
        """Return the set of user IDs in the given channel."""
        raw: set = await self._redis.smembers(self._channel_key(channel_name))
        return {int(m) for m in raw}

    async def get_member_count(self, channel_name: str) -> int:
        """Return the number of members in the given channel."""
        count = await self._redis.scard(self._channel_key(channel_name))
        return int(count)

    async def get_user_channels(self, user_id: int) -> set[str]:
        """Return the set of channel names the user has joined."""
        raw: set = await self._redis.smembers(self._user_key(user_id))
        return {str(c) for c in raw}

    async def remove_user_from_all(self, user_id: int) -> set[str]:
        """Remove the user from all channels.  Return set of removed channel names."""
        user_key = self._user_key(user_id)
        raw: set = await self._redis.smembers(user_key)
        if not raw:
            return set()

        channel_names = {str(c) for c in raw}

        async with self._redis.pipeline(transaction=True) as pipe:
            for channel_name in channel_names:
                _ = pipe.srem(self._channel_key(channel_name), user_id)
            _ = pipe.delete(user_key)
            _ = await pipe.execute()

        return channel_names
