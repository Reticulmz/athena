"""SQLAlchemy query-side role repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel
from osu_server.repositories.sqlalchemy.queries._shared import (
    SQLAlchemyQuerySessionFactory,
    role_to_domain,
)

if TYPE_CHECKING:
    from osu_server.domain.identity.roles import Role


class SQLAlchemyRoleQueryRepository:
    """Read-only role repository backed by short SQLAlchemy sessions."""

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        self._session_factory = session_factory

    async def get_by_id(self, role_id: int) -> Role | None:
        async with self._session_factory() as session:
            model = await session.get(RoleModel, role_id)
            return role_to_domain(model) if isinstance(model, RoleModel) else None

    async def get_by_name(self, name: str) -> Role | None:
        async with self._session_factory() as session:
            model = (
                await session.execute(select(RoleModel).where(RoleModel.name == name))
            ).scalar_one_or_none()
            return role_to_domain(model) if isinstance(model, RoleModel) else None

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        async with self._session_factory() as session:
            models = (
                (
                    await session.execute(
                        select(RoleModel)
                        .join(UserRoleModel, RoleModel.id == UserRoleModel.role_id)
                        .where(UserRoleModel.user_id == user_id)
                        .order_by(RoleModel.position.asc())
                    )
                )
                .scalars()
                .all()
            )
            return [role_to_domain(model) for model in models]

    async def get_default_role(self) -> Role:
        role = await self.get_by_name("Default")
        if role is None:
            msg = "No role named 'Default' exists"
            raise LookupError(msg)
        return role

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(UserRoleModel.user_id)
                    .where(UserRoleModel.role_id == role_id)
                    .order_by(UserRoleModel.user_id.asc())
                )
            ).all()
            return [row[0] for row in rows]
