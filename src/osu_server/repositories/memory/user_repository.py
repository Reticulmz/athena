"""InMemoryUserRepository — dict-based user repository for testing."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from osu_server.domain.user import User

if TYPE_CHECKING:
    from osu_server.domain.system_user import SystemUserIdentity


_BANCHO_BOT_USER_ID = 1


class InMemoryUserRepository:
    """In-memory implementation of the UserRepository Protocol.

    Uses plain dicts for storage with auto-incrementing id.
    Not thread-safe — intended for single-threaded test environments only.
    """

    def __init__(self) -> None:
        self._users_by_id: dict[int, User] = {}
        self._id_by_safe_username: dict[str, int] = {}
        self._id_by_email: dict[str, int] = {}
        self._disallowed_usernames: set[str] = set()
        self._next_id: int = 1

    async def create(self, user: User) -> User:
        """Persist a new user with an auto-generated id.

        Raises ``ValueError`` if ``safe_username`` or ``email`` already exists.
        """
        if user.safe_username.lower() in self._id_by_safe_username:
            msg = f"safe_username already exists: {user.safe_username}"
            raise ValueError(msg)

        if user.email.lower() in self._id_by_email:
            msg = f"email already exists: {user.email}"
            raise ValueError(msg)

        # Skip the reserved BanchoBot system user ID.
        if self._next_id == _BANCHO_BOT_USER_ID:
            self._next_id += 1

        created = replace(user, id=self._next_id)
        self._next_id += 1

        self._users_by_id[created.id] = created
        self._id_by_safe_username[created.safe_username.lower()] = created.id
        self._id_by_email[created.email.lower()] = created.id

        return created

    async def get_by_id(self, user_id: int) -> User | None:
        """Return the user with *user_id*, or ``None`` if not found."""
        return self._users_by_id.get(user_id)

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Return the user with *safe_username* (case-insensitive), or ``None``."""
        user_id = self._id_by_safe_username.get(safe_username.lower())
        if user_id is None:
            return None
        return self._users_by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Return the user with *email* (case-insensitive), or ``None``."""
        user_id = self._id_by_email.get(email.lower())
        if user_id is None:
            return None
        return self._users_by_id.get(user_id)

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """Return ``True`` if *safe_username* is in the disallowed list."""
        return safe_username.lower() in self._disallowed_usernames

    async def add_disallowed_username(self, safe_username: str) -> None:
        """Add *safe_username* to the disallowed list.  Idempotent."""
        self._disallowed_usernames.add(safe_username.lower())

    async def update_country(self, user_id: int, country: str) -> None:
        """Update the country code for *user_id*."""
        if user_id in self._users_by_id:
            user = self._users_by_id[user_id]
            self._users_by_id[user_id] = replace(user, country=country)

    async def sync_system_user(self, identity: SystemUserIdentity) -> None:
        safe = identity.username.lower().replace(" ", "_")
        conflict_id = self._id_by_safe_username.get(safe)
        if conflict_id is not None and conflict_id != _BANCHO_BOT_USER_ID:
            msg = f"configured BanchoBot safe username conflicts with existing user: {safe}"
            raise ValueError(msg)
        now = datetime.now(UTC)
        system_user = User(
            id=_BANCHO_BOT_USER_ID,
            username=identity.username,
            safe_username=safe,
            email="bot@internal",
            password_hash="!invalid",
            country="XX",
            created_at=now,
            updated_at=now,
        )
        self._users_by_id[_BANCHO_BOT_USER_ID] = system_user
        self._id_by_safe_username[safe] = _BANCHO_BOT_USER_ID
        self._id_by_email[system_user.email] = _BANCHO_BOT_USER_ID
        self._disallowed_usernames.add("banchobot")
        self._disallowed_usernames.add(safe)
