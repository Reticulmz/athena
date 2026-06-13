"""In-memory command-side role repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.identity.roles import Role
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryRoleCommandRepository:
    """Role command repository backed by an active in-memory UoW state."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    def add_role(self, role: Role) -> None:
        """Seed a role for tests that need command-side role checks."""
        self._state.roles_by_id[role.id] = role
        self._state.role_id_by_name[role.name] = role.id

    async def get_by_id(self, role_id: int) -> Role | None:
        return self._state.roles_by_id.get(role_id)

    async def get_by_name(self, name: str) -> Role | None:
        role_id = self._state.role_id_by_name.get(name)
        if role_id is None:
            return None
        return self._state.roles_by_id.get(role_id)

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        role_ids = self._state.role_ids_by_user_id.get(user_id, set())
        roles = [
            self._state.roles_by_id[role_id]
            for role_id in role_ids
            if role_id in self._state.roles_by_id
        ]
        return sorted(roles, key=lambda role: role.position)

    async def assign_role(self, user_id: int, role_id: int) -> None:
        self._state.role_ids_by_user_id.setdefault(user_id, set()).add(role_id)

    async def get_default_role(self) -> Role:
        role = await self.get_by_name("Default")
        if role is None:
            msg = "No role named 'Default' exists"
            raise LookupError(msg)
        return role

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        user_ids = [
            user_id
            for user_id, role_ids in self._state.role_ids_by_user_id.items()
            if role_id in role_ids
        ]
        return sorted(user_ids)
