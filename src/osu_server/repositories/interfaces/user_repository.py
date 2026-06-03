"""UserRepository Protocol — abstract interface for user persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.user import User


@runtime_checkable
class UserRepository(Protocol):
    """Protocol for user CRUD operations and disallowed username management.

    Preconditions:
        - ``safe_username`` arguments are already normalized
          (``User.normalize_username()`` applied).
    Postconditions:
        - ``create()`` returns a ``User`` with an auto-generated ``id``.
    """

    async def create(self, user: User) -> User:
        """Persist a new user and return it with a generated id.

        Raises ``ValueError`` if ``safe_username`` or ``email`` already exists.
        """
        ...

    async def get_by_id(self, user_id: int) -> User | None:
        """Return the user with *user_id*, or ``None`` if not found."""
        ...

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Return the user with *safe_username*, or ``None`` if not found."""
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Return the user with *email*, or ``None`` if not found."""
        ...

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """Return ``True`` if *safe_username* is in the disallowed list."""
        ...

    async def add_disallowed_username(self, safe_username: str) -> None:
        """Add *safe_username* to the disallowed list.  Idempotent."""
        ...

    async def update_country(self, user_id: int, country: str) -> None:
        """Update the country code for *user_id*."""
        ...
