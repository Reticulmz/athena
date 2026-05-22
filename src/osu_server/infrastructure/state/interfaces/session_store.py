"""SessionStore Protocol — abstract interface for session state management."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SessionStore(Protocol):
    """Protocol for session CRUD operations.

    Implementations must support create, get, get_by_user, delete, and exists.
    The ``data`` parameter is ``dict[str, object]`` for now; a typed Session
    dataclass will be introduced in the bancho-login spec.
    """

    async def create(self, user_id: int, token: str, data: dict[str, object]) -> None:
        """Store a session.  If the user already has a session, replace it."""
        ...

    async def get(self, token: str) -> dict[str, object] | None:
        """Return session data for *token*, or ``None`` if not found."""
        ...

    async def get_by_user(self, user_id: int) -> dict[str, object] | None:
        """Return session data for *user_id*, or ``None`` if not found."""
        ...

    async def delete(self, token: str) -> None:
        """Remove the session identified by *token*."""
        ...

    async def exists(self, token: str) -> bool:
        """Return ``True`` if a session with *token* exists."""
        ...

    async def refresh(self, token: str) -> bool:
        """Refresh the session TTL.  Return ``True`` if the session exists."""
        ...
