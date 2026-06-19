"""Command-side role repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.identity.roles import Role


@runtime_checkable
class RoleCommandRepository(Protocol):
    """Mutation and consistency-check port for roles and assignments."""

    async def get_by_id(self, role_id: int) -> Role | None:
        """Return the role with the internal role identifier."""
        ...

    async def get_by_name(self, name: str) -> Role | None:
        """Return the role with the name for command-side validation."""
        ...

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        """Return roles assigned to the user for authorization checks."""
        ...

    async def assign_role(self, user_id: int, role_id: int) -> None:
        """Assign a role to a user idempotently."""
        ...

    async def set_roles_for_user(self, user_id: int, role_ids: tuple[int, ...]) -> None:
        """Replace all roles assigned to a user with the given role identifiers."""
        ...

    async def get_default_role(self) -> Role:
        """Return the default role required by registration commands."""
        ...

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        """Return user ids assigned to a role for command-side propagation."""
        ...
