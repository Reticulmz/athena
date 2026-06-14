"""In-memory query-side role repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.identity.roles import Role
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryRoleQueryRepository:
    """Read-only role repository that reads from UoW factory's committed state."""

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def get_by_id(self, role_id: int) -> Role | None:
        state = self._factory.snapshot()
        return state.roles_by_id.get(role_id)

    async def get_by_name(self, name: str) -> Role | None:
        state = self._factory.snapshot()
        role_id = state.role_id_by_name.get(name)
        if role_id is None:
            return None
        return state.roles_by_id.get(role_id)

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        state = self._factory.snapshot()
        role_ids = state.role_ids_by_user_id.get(user_id, set())
        roles = [
            state.roles_by_id[role_id] for role_id in role_ids if role_id in state.roles_by_id
        ]
        return sorted(roles, key=lambda role: role.position)

    async def get_default_role(self) -> Role:
        role = await self.get_by_name("Default")
        if role is None:
            msg = "No role named 'Default' exists"
            raise LookupError(msg)
        return role

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        state = self._factory.snapshot()
        user_ids = [
            user_id
            for user_id, role_ids in state.role_ids_by_user_id.items()
            if role_id in role_ids
        ]
        return sorted(user_ids)
