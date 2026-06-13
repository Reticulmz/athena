"""Query-side role repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.roles import Role


class RoleQueryRepository(Protocol):
    """Read-only role access for authorization and display workflows."""

    async def get_by_id(self, role_id: int) -> Role | None:
        """Return the role with the identifier."""
        ...

    async def get_by_name(self, name: str) -> Role | None:
        """Return the role with the name."""
        ...

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        """Return roles assigned to a user."""
        ...

    async def get_default_role(self) -> Role:
        """Return the default role."""
        ...

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        """Return user ids assigned to a role."""
        ...
