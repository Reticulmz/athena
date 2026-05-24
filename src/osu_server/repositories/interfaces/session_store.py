"""SessionStore Protocol — abstract interface for session state management."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from osu_server.domain.session import (
    SessionData,  # noqa: TC001  # runtime_checkable needs runtime access
)


@runtime_checkable
class SessionStore(Protocol):
    """Protocol for session CRUD operations.

    Implementations must support create, get, get_by_user, delete, exists,
    and refresh.  Session data is represented by the ``SessionData`` dataclass.
    """

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        """Store a session.  If the user already has a session, replace it."""
        ...

    async def get(self, token: str) -> SessionData | None:
        """Return session data for *token*, or ``None`` if not found."""
        ...

    async def get_by_user(self, user_id: int) -> SessionData | None:
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
