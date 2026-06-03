"""ValkeySessionStore — Valkey-backed session store implementation."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, ClassVar

from glide import Script

from osu_server.domain.session import SessionData
from osu_server.domain.session_authorization import (
    SessionAuthorization,  # noqa: TC001  # runtime use via invoke_script args
)

if TYPE_CHECKING:
    from glide import GlideClient


class ValkeySessionStore:
    """Valkey implementation of the SessionStore Protocol.

    Key patterns:
        - ``{prefix}session:{token}`` -> JSON-encoded ``SessionData`` fields
        - ``{prefix}user_session:{user_id}`` -> token string

    Both keys share the same TTL.  When a user creates a new session while
    an old one exists, the old session is deleted first.

    Atomicity: ``create``, ``delete``, and ``refresh`` use Lua scripts
    (via Script objects / EVALSHA) to avoid TOCTOU races.
    """

    # KEYS[1] = user_session:{user_id}, KEYS[2] = session:{new_token}
    # ARGV[1] = session key prefix, ARGV[2] = JSON data, ARGV[3] = TTL, ARGV[4] = token
    _CREATE_SCRIPT: ClassVar[Script] = Script("""\
local old_token = redis.call('GET', KEYS[1])
if old_token then
    redis.call('DEL', ARGV[1] .. old_token)
end
redis.call('SET', KEYS[2], ARGV[2], 'EX', tonumber(ARGV[3]))
redis.call('SET', KEYS[1], ARGV[4], 'EX', tonumber(ARGV[3]))
return 1""")

    # KEYS[1] = session:{token}
    # ARGV[1] = TTL, ARGV[2] = user_id JSON field name, ARGV[3] = user key prefix
    _REFRESH_SCRIPT: ClassVar[Script] = Script("""\
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
return 1""")

    # KEYS[1] = user_session:{user_id}
    # ARGV[1] = session key prefix
    _DELETE_BY_USER_SCRIPT: ClassVar[Script] = Script("""\
local token = redis.call('GET', KEYS[1])
if not token then
    return 0
end
redis.call('DEL', ARGV[1] .. token)
redis.call('DEL', KEYS[1])
return 1""")

    # KEYS[1] = user_session:{user_id}
    # ARGV[1] = session key prefix
    # ARGV[2] = new privileges (int as string)
    # ARGV[3] = new role_ids (JSON array string)
    _UPDATE_AUTHORIZATION_SCRIPT: ClassVar[Script] = Script("""\
local token = redis.call('GET', KEYS[1])
if not token then
    return 0
end
local session_key = ARGV[1] .. token
local raw = redis.call('GET', session_key)
if not raw then
    return 0
end
local ttl = redis.call('TTL', session_key)
if ttl <= 0 then
    ttl = 3600
end
local data = cjson.decode(raw)
data['privileges'] = tonumber(ARGV[2])
data['role_ids'] = cjson.decode(ARGV[3])
redis.call('SET', session_key, cjson.encode(data), 'EX', ttl)
return 1""")

    # KEYS[1] = session:{token}
    # ARGV[1] = user_id JSON field name, ARGV[2] = user key prefix, ARGV[3] = token
    _DELETE_SCRIPT: ClassVar[Script] = Script("""\
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
return 1""")

    def __init__(
        self,
        client: GlideClient,
        *,
        ttl: int = 3600,
        key_prefix: str = "",
    ) -> None:
        self._client: GlideClient = client
        self._ttl: int = ttl
        self._prefix: str = key_prefix

    # -- key helpers ----------------------------------------------------------

    def _session_key(self, token: str) -> str:
        return f"{self._prefix}session:{token}"

    def _user_key(self, user_id: int) -> str:
        return f"{self._prefix}user_session:{user_id}"

    # -- SessionStore Protocol methods ----------------------------------------

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        """Store a session.  If the user already has one, remove the old session first."""
        _ = await self._client.invoke_script(
            self._CREATE_SCRIPT,
            keys=[self._user_key(user_id), self._session_key(token)],
            args=[
                f"{self._prefix}session:",
                json.dumps(asdict(data)),
                str(self._ttl),
                token,
            ],
        )

    async def get(self, token: str) -> SessionData | None:
        """Return session data for *token*, or ``None`` if not found."""
        raw = await self._client.get(self._session_key(token))
        if raw is None:
            return None
        return SessionData(**json.loads(raw))  # pyright: ignore[reportAny] — json.loads returns Any

    async def get_by_user(self, user_id: int) -> SessionData | None:
        """Return session data for *user_id*, or ``None`` if not found."""
        token_raw = await self._client.get(self._user_key(user_id))
        if token_raw is None:
            return None
        token = token_raw.decode()
        return await self.get(token)

    async def delete(self, token: str) -> None:
        """Remove the session identified by *token*.

        Also removes the reverse ``user_session:{user_id}`` mapping, but only
        if it still points to this token (avoids destroying a newer session
        created by a concurrent login).
        """
        _ = await self._client.invoke_script(
            self._DELETE_SCRIPT,
            keys=[self._session_key(token)],
            args=[
                "user_id",
                f"{self._prefix}user_session:",
                token,
            ],
        )

    async def exists(self, token: str) -> bool:
        """Return ``True`` if a session with *token* exists."""
        result = await self._client.exists([self._session_key(token)])
        return result > 0

    async def refresh(self, token: str) -> bool:
        """Atomically reset the TTL on both session and user-mapping keys.

        Returns ``True`` if the session exists and was refreshed.
        """
        result = await self._client.invoke_script(
            self._REFRESH_SCRIPT,
            keys=[self._session_key(token)],
            args=[
                str(self._ttl),
                "user_id",
                f"{self._prefix}user_session:",
            ],
        )
        return bool(result)

    async def delete_by_user(self, user_id: int) -> None:
        """Remove the session for *user_id*.  No-op if not found (idempotent)."""
        _ = await self._client.invoke_script(
            self._DELETE_BY_USER_SCRIPT,
            keys=[self._user_key(user_id)],
            args=[f"{self._prefix}session:"],
        )

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        """Atomically patch ``privileges`` and ``role_ids`` in the active session.

        Preserves all other fields, the user-to-token mapping, and the
        remaining TTL on the session key.  Returns ``False`` when no active
        session exists for *user_id*.
        """
        result = await self._client.invoke_script(
            self._UPDATE_AUTHORIZATION_SCRIPT,
            keys=[self._user_key(user_id)],
            args=[
                f"{self._prefix}session:",
                str(int(authorization.privileges)),
                json.dumps(list(authorization.role_ids)),
            ],
        )
        return bool(result)

    async def get_all_user_ids(self) -> list[int]:
        """Return all active user IDs by scanning ``user_session:*`` keys."""
        prefix = f"{self._prefix}user_session:"
        user_ids: list[int] = []
        cursor = "0"
        while True:
            cursor_str, keys = await self._client.scan(cursor, match=prefix + "*", count=100)
            for key in keys:
                raw_str = key.decode() if isinstance(key, bytes) else str(key)
                user_id_str = raw_str.removeprefix(prefix)
                user_ids.append(int(user_id_str))
            cursor = cursor_str.decode() if isinstance(cursor_str, bytes) else str(cursor_str)
            if cursor == "0":
                break
        return user_ids
