"""SQLAlchemyRoleRepository — async database-backed role repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: TC002

from osu_server.domain.role import Privileges, Role
from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel


class SQLAlchemyRoleRepository:
    """SQLAlchemy implementation of the RoleRepository Protocol.

    Uses ``async_sessionmaker`` for database access.  Each method opens
    its own session to keep transactions short.
    """

    _session_factory: async_sessionmaker[AsyncSession]

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_by_id(self, role_id: int) -> Role | None:
        """Return the role with *role_id*, or ``None`` if not found."""
        async with self._session_factory() as session:
            model = await session.get(RoleModel, role_id)
            return self._to_domain(model) if model is not None else None

    async def get_by_name(self, name: str) -> Role | None:
        """Return the role with *name*, or ``None`` if not found."""
        async with self._session_factory() as session:
            stmt = select(RoleModel).where(RoleModel.name == name)
            model = (await session.execute(stmt)).scalar_one_or_none()
            return self._to_domain(model) if model is not None else None

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        """Return all roles assigned to *user_id*, sorted by position ascending."""
        async with self._session_factory() as session:
            stmt = (
                select(RoleModel)
                .join(UserRoleModel, RoleModel.id == UserRoleModel.role_id)
                .where(UserRoleModel.user_id == user_id)
                .order_by(RoleModel.position.asc())
            )
            result = await session.execute(stmt)
            return [self._to_domain(model) for model in result.scalars()]

    async def assign_role(self, user_id: int, role_id: int) -> None:
        """Assign role *role_id* to user *user_id*.  Idempotent."""
        async with self._session_factory() as session:
            stmt = select(UserRoleModel).where(
                UserRoleModel.user_id == user_id,
                UserRoleModel.role_id == role_id,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                return

            model = UserRoleModel(user_id=user_id, role_id=role_id)
            session.add(model)
            await session.commit()

    async def get_default_role(self) -> Role:
        """Return the role named ``"Default"``.

        Raises ``LookupError`` if no such role exists.
        """
        role = await self.get_by_name("Default")
        if role is None:
            msg = "No role named 'Default' exists"
            raise LookupError(msg)
        return role

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        """Return user IDs assigned to *role_id*, sorted ascending."""
        _ = role_id
        raise NotImplementedError

    @staticmethod
    def _to_domain(model: RoleModel) -> Role:
        """Map a SQLAlchemy RoleModel to a domain Role."""
        return Role(
            id=model.id,
            name=model.name,
            permissions=Privileges(model.permissions),
            position=model.position,
        )
