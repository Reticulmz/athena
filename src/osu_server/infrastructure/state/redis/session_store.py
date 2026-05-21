# pyright: reportAny=false
"""RedisSessionStore — Redis-backed session store implementation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisSessionStore:
    """Redis implementation of the SessionStore Protocol.

    Key patterns:
        - ``{prefix}session:{token}`` → JSON-encoded session data (with
          internal ``_user_id`` field for reverse-lookup support)
        - ``{prefix}user_session:{user_id}`` → token string

    Both keys share the same TTL.  When a user creates a new session while
    an old one exists, the old session is deleted first.

    The internal ``_user_id`` field is stripped from the data returned by
    ``get`` and ``get_by_user`` so callers see exactly the dict they stored.
    """

    _INTERNAL_USER_ID_KEY: Final[str] = "_user_id"

    def __init__(
        self,
        redis: Redis,
        *,
        ttl: int = 3600,
        key_prefix: str = "",
    ) -> None:
        self._redis: Redis = redis
        self._ttl: int = ttl
        self._prefix: str = key_prefix

    # -- key helpers ----------------------------------------------------------

    def _session_key(self, token: str) -> str:
        return f"{self._prefix}session:{token}"

    def _user_key(self, user_id: int) -> str:
        return f"{self._prefix}user_session:{user_id}"

    # -- internal helpers -----------------------------------------------------

    @staticmethod
    def _strip_internal(data: dict[str, object]) -> dict[str, object]:
        """Return a copy of *data* without internal bookkeeping fields."""
        return {k: v for k, v in data.items() if k != RedisSessionStore._INTERNAL_USER_ID_KEY}

    # -- SessionStore Protocol methods ----------------------------------------

    async def create(self, user_id: int, token: str, data: dict[str, object]) -> None:
        """Store a session.  If the user already has one, remove the old session first."""
        # Evict previous session for this user (if any)
        old_token_raw = await self._redis.get(self._user_key(user_id))
        if old_token_raw is not None:
            old_token = (
                old_token_raw.decode() if isinstance(old_token_raw, bytes) else str(old_token_raw)
            )
            await self._redis.delete(self._session_key(old_token))

        # Embed user_id so delete() can build the reverse key without scanning.
        stored = {**data, self._INTERNAL_USER_ID_KEY: user_id}

        pipe = self._redis.pipeline()
        _ = pipe.set(self._session_key(token), json.dumps(stored), ex=self._ttl)
        _ = pipe.set(self._user_key(user_id), token, ex=self._ttl)
        _ = await pipe.execute()

    async def get(self, token: str) -> dict[str, object] | None:
        """Return session data for *token*, or ``None`` if not found."""
        raw = await self._redis.get(self._session_key(token))
        if raw is None:
            return None
        payload: str = raw.decode() if isinstance(raw, bytes) else str(raw)
        result: dict[str, object] = json.loads(payload)
        return self._strip_internal(result)

    async def get_by_user(self, user_id: int) -> dict[str, object] | None:
        """Return session data for *user_id*, or ``None`` if not found."""
        token_raw = await self._redis.get(self._user_key(user_id))
        if token_raw is None:
            return None
        token: str = token_raw.decode() if isinstance(token_raw, bytes) else str(token_raw)
        return await self.get(token)

    async def delete(self, token: str) -> None:
        """Remove the session identified by *token*.

        Also removes the reverse ``user_session:{user_id}`` mapping so that
        ``get_by_user`` no longer finds this session.
        """
        # Read the session first to recover the embedded user_id.
        raw = await self._redis.get(self._session_key(token))
        if raw is None:
            # Nothing to delete.
            return

        payload: str = raw.decode() if isinstance(raw, bytes) else str(raw)
        data: dict[str, object] = json.loads(payload)
        user_id = data.get(self._INTERNAL_USER_ID_KEY)

        keys_to_delete = [self._session_key(token)]
        if user_id is not None:
            keys_to_delete.append(self._user_key(int(str(user_id))))

        await self._redis.delete(*keys_to_delete)

    async def exists(self, token: str) -> bool:
        """Return ``True`` if a session with *token* exists."""
        result = await self._redis.exists(self._session_key(token))
        return int(str(result)) > 0
