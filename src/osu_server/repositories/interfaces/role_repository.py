"""RoleRepository Protocol — abstract interface for role persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.role import Role


@runtime_checkable
class RoleRepository(Protocol):
    """Protocol for role retrieval, assignment, and default role lookup.

    Postconditions:
        - ``get_roles_for_user()`` returns roles sorted by ``position`` ascending.
        - ``get_default_role()`` raises ``LookupError`` if no "Default" role exists.
    """

    async def get_by_id(self, role_id: int) -> Role | None:
        """Return the role with *role_id*, or ``None`` if not found."""
        ...

    async def get_by_name(self, name: str) -> Role | None:
        """Return the role with *name*, or ``None`` if not found."""
        ...

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        """Return all roles assigned to *user_id*, sorted by position ascending."""
        ...

    async def assign_role(self, user_id: int, role_id: int) -> None:
        """Assign role *role_id* to user *user_id*.  Idempotent."""
        ...

    async def get_default_role(self) -> Role:
        """Return the role named ``"Default"``.

        Raises ``LookupError`` if no such role exists.
        """
        ...

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        """Return user IDs assigned to *role_id*, sorted ascending.

        Preconditions:
            - ``role_id`` is an internal role identifier.

        Postconditions:
            - Returns ``list[int]`` — user IDs assigned to the role.
            - Returns empty list when no assignments exist.
            - Returned user IDs are deterministic, sorted ascending.
        """
        ...
