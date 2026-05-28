"""ValkeyChannelStateStore — Valkey-backed channel membership store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from glide import Batch

if TYPE_CHECKING:
    from glide import GlideClient


class ValkeyChannelStateStore:
    """Valkey implementation of the ChannelStateStore Protocol.

    Key patterns:
        - ``{prefix}channel:{name}:members`` -> Set of user_id
        - ``{prefix}user:{user_id}:channels`` -> Set of channel_name

    Bidirectional indices are updated atomically via Batch(is_atomic=True).
    No TTL -- membership is managed explicitly via add/remove/remove_user_from_all.
    """

    def __init__(self, client: GlideClient, *, key_prefix: str = "") -> None:
        self._client: GlideClient = client
        self._prefix: str = key_prefix

    # -- key helpers ----------------------------------------------------------

    def _channel_key(self, channel_name: str) -> str:
        return f"{self._prefix}channel:{channel_name}:members"

    def _user_key(self, user_id: int) -> str:
        return f"{self._prefix}user:{user_id}:channels"

    # -- ChannelStateStore Protocol methods -----------------------------------

    async def add_member(self, channel_name: str, user_id: int) -> None:
        """Add a user to a channel.  Both Sets updated atomically."""
        batch = Batch(is_atomic=True)
        _ = batch.sadd(self._channel_key(channel_name), [str(user_id)])
        _ = batch.sadd(self._user_key(user_id), [channel_name])
        _ = await self._client.exec(batch, raise_on_error=True)

    async def remove_member(self, channel_name: str, user_id: int) -> None:
        """Remove a user from a channel.  Both Sets updated atomically."""
        batch = Batch(is_atomic=True)
        _ = batch.srem(self._channel_key(channel_name), [str(user_id)])
        _ = batch.srem(self._user_key(user_id), [channel_name])
        _ = await self._client.exec(batch, raise_on_error=True)

    async def is_member(self, channel_name: str, user_id: int) -> bool:
        """Return True if the user is a member of the channel."""
        return await self._client.sismember(self._channel_key(channel_name), str(user_id))

    async def get_members(self, channel_name: str) -> set[int]:
        """Return the set of user IDs in the given channel."""
        raw = await self._client.smembers(self._channel_key(channel_name))
        return {int(m) for m in raw}

    async def get_member_count(self, channel_name: str) -> int:
        """Return the number of members in the given channel."""
        return await self._client.scard(self._channel_key(channel_name))

    async def get_user_channels(self, user_id: int) -> set[str]:
        """Return the set of channel names the user has joined."""
        raw = await self._client.smembers(self._user_key(user_id))
        return {m.decode() for m in raw}

    async def remove_user_from_all(self, user_id: int) -> set[str]:
        """Remove the user from all channels.  Return set of removed channel names."""
        user_key = self._user_key(user_id)
        raw = await self._client.smembers(user_key)
        if not raw:
            return set()

        channel_names = {m.decode() for m in raw}

        batch = Batch(is_atomic=True)
        for channel_name in channel_names:
            _ = batch.srem(self._channel_key(channel_name), [str(user_id)])
        _ = batch.delete([user_key])
        _ = await self._client.exec(batch, raise_on_error=True)

        return channel_names
