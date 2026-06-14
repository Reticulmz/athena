"""In-memory query-side user repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.identity.users import User
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryUserQueryRepository:
    """Read-only user repository that reads from UoW factory's committed state."""

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def get_by_id(self, user_id: int) -> User | None:
        state = self._factory.snapshot()
        return state.users_by_id.get(user_id)

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        state = self._factory.snapshot()
        user_id = state.user_id_by_safe_username.get(safe_username.lower())
        if user_id is None:
            return None
        return state.users_by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        state = self._factory.snapshot()
        user_id = state.user_id_by_email.get(email.lower())
        if user_id is None:
            return None
        return state.users_by_id.get(user_id)

    async def is_username_disallowed(self, safe_username: str) -> bool:
        state = self._factory.snapshot()
        return safe_username.lower() in state.disallowed_usernames
