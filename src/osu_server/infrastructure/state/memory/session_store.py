"""InMemorySessionStore — dict-based session store for testing."""

from __future__ import annotations


class InMemorySessionStore:
    """In-memory implementation of the SessionStore Protocol.

    Uses plain dicts keyed by token and user_id.  Not thread-safe —
    intended for single-threaded test environments only.
    """

    def __init__(self) -> None:
        self._by_token: dict[str, dict[str, object]] = {}
        self._user_to_token: dict[int, str] = {}
        self._token_to_user: dict[str, int] = {}

    async def create(self, user_id: int, token: str, data: dict[str, object]) -> None:
        """Store a session.  If the user already has one, remove the old session first."""
        old_token = self._user_to_token.get(user_id)
        if old_token is not None:
            _ = self._by_token.pop(old_token, None)
            _ = self._token_to_user.pop(old_token, None)

        self._by_token[token] = data
        self._user_to_token[user_id] = token
        self._token_to_user[token] = user_id

    async def get(self, token: str) -> dict[str, object] | None:
        """Return a copy of session data for *token*, or ``None`` if not found."""
        data = self._by_token.get(token)
        return dict(data) if data is not None else None

    async def get_by_user(self, user_id: int) -> dict[str, object] | None:
        """Return a copy of session data for *user_id*, or ``None`` if not found."""
        token = self._user_to_token.get(user_id)
        if token is None:
            return None
        data = self._by_token.get(token)
        return dict(data) if data is not None else None

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
