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

    Atomicity: ``create`` and ``delete`` use Lua scripts to avoid TOCTOU
    races between the session and user-mapping keys.
    """

    _INTERNAL_USER_ID_KEY: Final[str] = "_user_id"

    # Lua script: atomically evict old session (if any) and write new session.
    # KEYS[1] = user_session:{user_id}, KEYS[2] = session:{new_token}
    # ARGV[1] = session key prefix, ARGV[2] = JSON data, ARGV[3] = TTL, ARGV[4] = token
    _CREATE_SCRIPT: Final[str] = """\
local old_token = redis.call('GET', KEYS[1])
if old_token then
    redis.call('DEL', ARGV[1] .. old_token)
end
redis.call('SET', KEYS[2], ARGV[2], 'EX', tonumber(ARGV[3]))
redis.call('SET', KEYS[1], ARGV[4], 'EX', tonumber(ARGV[3]))
return 1"""

    # Lua script: atomically refresh TTL on both session and user-mapping keys.
    # KEYS[1] = session:{token}
    # ARGV[1] = TTL, ARGV[2] = internal user ID field name, ARGV[3] = user key prefix
    _REFRESH_SCRIPT: Final[str] = """\
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 0
end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
local data = cjson.decode(raw)
local user_id = data[ARGV[2]]
if user_id ~= nil then
    local user_key = ARGV[3] .. tostring(math.floor(user_id))
    redis.call('EXPIRE', user_key, tonumber(ARGV[1]))
end
return 1"""

    # Lua script: atomically delete session and its user mapping (only if
    # the user mapping still points to this token — prevents racing with a
    # concurrent create that already overwrote the mapping).
    # KEYS[1] = session:{token}
    # ARGV[1] = internal user ID field name, ARGV[2] = user key prefix, ARGV[3] = token
    _DELETE_SCRIPT: Final[str] = """\
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 0
end
local data = cjson.decode(raw)
local user_id = data[ARGV[1]]
if user_id ~= nil then
    local user_key = ARGV[2] .. tostring(math.floor(user_id))
    local current_token = redis.call('GET', user_key)
    if current_token == ARGV[3] then
        redis.call('DEL', user_key)
    end
end
redis.call('DEL', KEYS[1])
return 1"""

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
        stored = {**data, self._INTERNAL_USER_ID_KEY: user_id}
        _ = await self._redis.eval(  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
            self._CREATE_SCRIPT,
            2,
            self._user_key(user_id),
            self._session_key(token),
            f"{self._prefix}session:",
            json.dumps(stored),
            str(self._ttl),
            token,
        )

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

        Also removes the reverse ``user_session:{user_id}`` mapping, but only
        if it still points to this token (avoids destroying a newer session
        created by a concurrent login).
        """
        _ = await self._redis.eval(  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
            self._DELETE_SCRIPT,
            1,
            self._session_key(token),
            self._INTERNAL_USER_ID_KEY,
            f"{self._prefix}user_session:",
            token,
        )

    async def exists(self, token: str) -> bool:
        """Return ``True`` if a session with *token* exists."""
        result = await self._redis.exists(self._session_key(token))
        return bool(result)

    async def refresh(self, token: str) -> bool:
        """Atomically reset the TTL on both session and user-mapping keys.

        Returns ``True`` if the session exists and was refreshed.
        Uses a Lua script for atomicity, consistent with ``create``/``delete``.
        """
        result = await self._redis.eval(  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
            self._REFRESH_SCRIPT,
            1,
            self._session_key(token),
            str(self._ttl),
            self._INTERNAL_USER_ID_KEY,
            f"{self._prefix}user_session:",
        )
        return bool(result)  # pyright: ignore[reportUnknownArgumentType]
