"""InMemoryRoleRepository — dict-based role repository for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from osu_server.domain.role import Role


class InMemoryRoleRepository:
    """In-memory implementation of the RoleRepository Protocol.

    Accepts optional *seed_roles* in the constructor for pre-populated data.
    Not thread-safe — intended for single-threaded test environments only.
    """

    def __init__(self, seed_roles: Sequence[Role] | None = None) -> None:
        self._roles_by_id: dict[int, Role] = {}
        self._roles_by_name: dict[str, int] = {}
        self._user_roles: dict[int, set[int]] = {}

        if seed_roles is not None:
            for role in seed_roles:
                self._roles_by_id[role.id] = role
                self._roles_by_name[role.name] = role.id

    def add_role(self, role: Role) -> None:
        """Add a role to the in-memory repository for testing."""
        self._roles_by_id[role.id] = role
        self._roles_by_name[role.name] = role.id

    async def get_by_id(self, role_id: int) -> Role | None:
        """Return the role with *role_id*, or ``None`` if not found."""
        return self._roles_by_id.get(role_id)

    async def get_by_name(self, name: str) -> Role | None:
        """Return the role with *name*, or ``None`` if not found."""
        role_id = self._roles_by_name.get(name)
        if role_id is None:
            return None
        return self._roles_by_id.get(role_id)

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        """Return all roles assigned to *user_id*, sorted by position ascending."""
        role_ids = self._user_roles.get(user_id, set())
        roles = [self._roles_by_id[rid] for rid in role_ids if rid in self._roles_by_id]
        return sorted(roles, key=lambda r: r.position)

    async def assign_role(self, user_id: int, role_id: int) -> None:
        """Assign role *role_id* to user *user_id*.  Idempotent."""
        if user_id not in self._user_roles:
            self._user_roles[user_id] = set()
        self._user_roles[user_id].add(role_id)

    async def get_default_role(self) -> Role:
        """Return the role named ``"Default"``.

        Raises ``LookupError`` if no such role exists.
        """
        role = await self.get_by_name("Default")
        if role is None:
            msg = "No role named 'Default' exists"
            raise LookupError(msg)
        return role
