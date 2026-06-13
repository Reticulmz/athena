"""InMemorySessionStore — dict-based session store for testing."""

from __future__ import annotations

from dataclasses import replace

from osu_server.domain.identity.sessions import (
    SessionAuthorization,  # noqa: TC001
    SessionData,  # noqa: TC001
)


class InMemorySessionStore:
    """In-memory implementation of the SessionStore Protocol.

    Uses plain dicts keyed by token and user_id.  Not thread-safe —
    intended for single-threaded test environments only.
    """

    def __init__(self) -> None:
        self._by_token: dict[str, SessionData] = {}
        self._user_to_token: dict[int, str] = {}
        self._token_to_user: dict[str, int] = {}

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        """Store a session.  If the user already has one, remove the old session first."""
        old_token = self._user_to_token.get(user_id)
        if old_token is not None:
            _ = self._by_token.pop(old_token, None)
            _ = self._token_to_user.pop(old_token, None)

        self._by_token[token] = data
        self._user_to_token[user_id] = token
        self._token_to_user[token] = user_id

    async def get(self, token: str) -> SessionData | None:
        """Return a copy of session data for *token*, or ``None`` if not found."""
        data = self._by_token.get(token)
        return replace(data) if data is not None else None

    async def get_by_user(self, user_id: int) -> SessionData | None:
        """Return a copy of session data for *user_id*, or ``None`` if not found."""
        token = self._user_to_token.get(user_id)
        if token is None:
            return None
        data = self._by_token.get(token)
        return replace(data) if data is not None else None

    async def delete(self, token: str) -> None:
        """Remove the session identified by *token*."""
        data = self._by_token.pop(token, None)
        if data is not None:
            user_id = self._token_to_user.pop(token, None)
            if user_id is not None and self._user_to_token.get(user_id) == token:
                del self._user_to_token[user_id]

    async def exists(self, token: str) -> bool:
        """Return ``True`` if a session with *token* exists."""
        return token in self._by_token

    async def refresh(self, token: str) -> bool:
        """Refresh the session TTL.

        In-memory store has no TTL concept, so this is a pure existence check.
        """
        return token in self._by_token

    async def delete_by_user(self, user_id: int) -> None:
        """Remove the session for *user_id*.  No-op if not found (idempotent)."""
        token = self._user_to_token.pop(user_id, None)
        if token is None:
            return
        _ = self._by_token.pop(token, None)
        _ = self._token_to_user.pop(token, None)

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        """Update only privileges and role_ids of an active session.

        Returns ``True`` if the session was updated, ``False`` if no active
        session exists for *user_id*.  Does not create a new session, delete
        the session, or change any non-authorization fields.
        """
        token = self._user_to_token.get(user_id)
        if token is None:
            return False

        session = self._by_token[token]
        self._by_token[token] = replace(
            session,
            privileges=int(authorization.privileges),
            role_ids=authorization.role_ids,
        )
        return True

    async def get_all_user_ids(self) -> list[int]:
        """Return all active user IDs."""
        return list(self._user_to_token.keys())
