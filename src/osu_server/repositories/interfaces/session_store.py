"""Session runtime Protocols for caller-specific session state access."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from osu_server.domain.identity.sessions import (
    SessionAuthorization,  # noqa: TC001  # runtime_checkable needs runtime access
    SessionData,  # noqa: TC001  # runtime_checkable needs runtime access
)


@runtime_checkable
class LoginSessionWriter(Protocol):
    """Session capability needed by successful login."""

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        """Store a session.  If the user already has a session, replace it."""
        ...


@runtime_checkable
class PollingSessionRuntime(Protocol):
    """Session capability needed by stable polling."""

    async def get(self, token: str) -> SessionData | None:
        """Return session data for *token*, or ``None`` if not found."""
        ...

    async def refresh(self, token: str) -> bool:
        """Refresh the session TTL.  Return ``True`` if the session exists."""
        ...


@runtime_checkable
class UserSessionLookup(Protocol):
    """Session capability needed by user-targeted online checks."""

    async def get_by_user(self, user_id: int) -> SessionData | None:
        """Return session data for *user_id*, or ``None`` if not found."""
        ...


@runtime_checkable
class SessionLifecycleRuntime(Protocol):
    """Session capability needed by disconnect handling."""

    async def delete(self, token: str) -> None:
        """Remove the session identified by *token*."""
        ...

    async def exists(self, token: str) -> bool:
        """Return ``True`` if a session with *token* exists."""
        ...

    async def delete_by_user(self, user_id: int) -> None:
        """Remove the session for *user_id*.

        If no session exists for the given user, this is a no-op (idempotent).
        """
        ...


@runtime_checkable
class SessionAuthorizationRuntime(Protocol):
    """Session capability needed by authorization refresh."""

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


@runtime_checkable
class SessionPrivacyRuntime(Protocol):
    """Session capability needed by privacy mutation."""

    async def update_pm_private(self, user_id: int, enabled: bool) -> bool:
        """Update only pm_private of an active session.

        Returns ``True`` if the session was updated, ``False`` if no active
        session exists for *user_id*.  Does not create a new session, delete
        the session, or change any non-privacy fields.
        """
        ...


@runtime_checkable
class ActiveSessionRoster(Protocol):
    """Session capability needed by stable online roster reads."""

    async def list_active_sessions(self) -> list[SessionData]:
        """Return session data for all active sessions."""
        ...


@runtime_checkable
class SessionStore(
    LoginSessionWriter,
    PollingSessionRuntime,
    UserSessionLookup,
    SessionLifecycleRuntime,
    SessionAuthorizationRuntime,
    SessionPrivacyRuntime,
    ActiveSessionRoster,
    Protocol,
):
    """Full storage adapter interface implemented by Valkey and memory stores."""


__all__ = [
    "ActiveSessionRoster",
    "LoginSessionWriter",
    "PollingSessionRuntime",
    "SessionAuthorizationRuntime",
    "SessionLifecycleRuntime",
    "SessionPrivacyRuntime",
    "SessionStore",
    "UserSessionLookup",
]
