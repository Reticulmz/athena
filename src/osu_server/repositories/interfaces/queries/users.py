"""Query-side user repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.users import User


class UserQueryRepository(Protocol):
    """Read-only user access for display and lookup workflows."""

    async def get_by_id(self, user_id: int) -> User | None:
        """Return the user with the identifier."""
        ...

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Return the user with the normalized username."""
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Return the user with the email address."""
        ...
