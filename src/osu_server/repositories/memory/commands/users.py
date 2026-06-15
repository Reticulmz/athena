"""In-memory command-side user repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from osu_server.domain.identity.users import User
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState, now_utc

if TYPE_CHECKING:
    from osu_server.domain.identity.system_users import SystemUserIdentity

_BANCHO_BOT_USER_ID = 1


class InMemoryUserCommandRepository:
    """User command repository backed by an active in-memory UoW state."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    async def create(self, user: User) -> User:
        safe_username = user.safe_username.lower()
        email = user.email.lower()
        if safe_username in self._state.user_id_by_safe_username:
            msg = f"safe_username already exists: {user.safe_username}"
            raise ValueError(msg)
        if email in self._state.user_id_by_email:
            msg = f"email already exists: {user.email}"
            raise ValueError(msg)

        if self._state.next_user_id == _BANCHO_BOT_USER_ID:
            self._state.next_user_id += 1

        created = replace(user, id=self._state.next_user_id)
        self._state.next_user_id += 1
        self._state.users_by_id[created.id] = created
        self._state.user_id_by_safe_username[safe_username] = created.id
        self._state.user_id_by_email[email] = created.id
        return created

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        user_id = self._state.user_id_by_safe_username.get(safe_username.lower())
        if user_id is None:
            return None
        return self._state.users_by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        user_id = self._state.user_id_by_email.get(email.lower())
        if user_id is None:
            return None
        return self._state.users_by_id.get(user_id)

    async def is_username_disallowed(self, safe_username: str) -> bool:
        return safe_username.lower() in self._state.disallowed_usernames

    async def add_disallowed_username(self, safe_username: str) -> None:
        self._state.disallowed_usernames.add(safe_username.lower())

    async def update_country(self, user_id: int, country: str) -> None:
        existing = self._state.users_by_id.get(user_id)
        if existing is not None:
            self._state.users_by_id[user_id] = replace(existing, country=country)

    async def update_password_hash(self, user_id: int, password_hash: str) -> bool:
        existing = self._state.users_by_id.get(user_id)
        if existing is None:
            return False
        self._state.users_by_id[user_id] = replace(
            existing,
            password_hash=password_hash,
            updated_at=now_utc(),
        )
        return True

    async def sync_system_user(self, identity: SystemUserIdentity) -> None:
        safe_username = User.normalize_username(identity.username)
        conflict_id = self._state.user_id_by_safe_username.get(safe_username)
        if conflict_id is not None and conflict_id != _BANCHO_BOT_USER_ID:
            msg = f"configured system username conflicts with existing user: {safe_username}"
            raise ValueError(msg)

        now = datetime.now(UTC)
        system_user = User(
            id=_BANCHO_BOT_USER_ID,
            username=identity.username,
            safe_username=safe_username,
            email="bot@internal",
            password_hash="!invalid",
            country="XX",
            created_at=now,
            updated_at=now,
        )
        self._state.users_by_id[_BANCHO_BOT_USER_ID] = system_user
        self._state.user_id_by_safe_username[safe_username] = _BANCHO_BOT_USER_ID
        self._state.user_id_by_email[system_user.email] = _BANCHO_BOT_USER_ID
        self._state.disallowed_usernames.add("banchobot")
        self._state.disallowed_usernames.add(safe_username)
