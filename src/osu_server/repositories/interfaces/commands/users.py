"""Command-side user repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.system_users import SystemUserIdentity
    from osu_server.domain.identity.users import User


class UserCommandRepository(Protocol):
    """Mutation and consistency-check port for users."""

    async def create(self, user: User) -> User:
        """Persist a new user and return it with repository-assigned identity."""
        ...

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Return the user with the normalized username for uniqueness checks."""
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Return the user with the email address for uniqueness checks."""
        ...

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """Return whether the normalized username is reserved."""
        ...

    async def add_disallowed_username(self, safe_username: str) -> None:
        """Reserve a normalized username."""
        ...

    async def update_country(self, user_id: int, country: str) -> None:
        """Persist a user's country code."""
        ...

    async def sync_system_user(self, identity: SystemUserIdentity) -> None:
        """Ensure the configured system user record and reservations exist."""
        ...
