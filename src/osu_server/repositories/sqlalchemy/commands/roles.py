"""SQLAlchemy command-side role repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyRoleCommandRepository:
    """Role command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def get_by_id(self, role_id: int) -> Role | None:
        model = await self._session.get(RoleModel, role_id)
        return _role_to_domain(model) if isinstance(model, RoleModel) else None

    async def get_by_name(self, name: str) -> Role | None:
        model = (
            await self._session.execute(select(RoleModel).where(RoleModel.name == name))
        ).scalar_one_or_none()
        return _role_to_domain(model) if isinstance(model, RoleModel) else None

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        models = (
            (
                await self._session.execute(
                    select(RoleModel)
                    .join(UserRoleModel, RoleModel.id == UserRoleModel.role_id)
                    .where(UserRoleModel.user_id == user_id)
                    .order_by(RoleModel.position.asc())
                )
            )
            .scalars()
            .all()
        )
        return [_role_to_domain(model) for model in models]

    async def assign_role(self, user_id: int, role_id: int) -> None:
        existing = (
            await self._session.execute(
                select(UserRoleModel).where(
                    UserRoleModel.user_id == user_id,
                    UserRoleModel.role_id == role_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        self._session.add(UserRoleModel(user_id=user_id, role_id=role_id))
        await self._session.flush()

    async def get_default_role(self) -> Role:
        role = await self.get_by_name("Default")
        if role is None:
            msg = "No role named 'Default' exists"
            raise LookupError(msg)
        return role

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        rows = (
            await self._session.execute(
                select(UserRoleModel.user_id)
                .where(UserRoleModel.role_id == role_id)
                .order_by(UserRoleModel.user_id.asc())
            )
        ).all()
        return [row[0] for row in rows]


def _role_to_domain(model: RoleModel) -> Role:
    return Role(
        id=model.id,
        name=model.name,
        permissions=Privileges(model.permissions),
        position=model.position,
    )
