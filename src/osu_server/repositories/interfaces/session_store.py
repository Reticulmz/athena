"""SessionStore Protocol — abstract interface for session state management."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from osu_server.domain.identity.sessions import (
    SessionAuthorization,  # noqa: TC001  # runtime_checkable needs runtime access
    SessionData,  # noqa: TC001  # runtime_checkable needs runtime access
)


@runtime_checkable
class SessionStore(Protocol):
    """Protocol for session CRUD operations.

    Implementations must support create, get, get_by_user, delete,
    delete_by_user, exists, refresh, update_authorization, and list_active_sessions.
    Session data is represented by the ``SessionData`` dataclass.
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

    async def delete_by_user(self, user_id: int) -> None:
        """Remove the session for *user_id*.

        If no session exists for the given user, this is a no-op (idempotent).
        """
        ...

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
        ...

    async def update_pm_private(self, user_id: int, enabled: bool) -> bool:
        """Update only pm_private of an active session.

        Returns ``True`` if the session was updated, ``False`` if no active
        session exists for *user_id*.  Does not create a new session, delete
        the session, or change any non-privacy fields.
        """
        ...

    async def list_active_sessions(self) -> list[SessionData]:
        """Return session data for all active sessions."""
        ...
