"""SQLAlchemyからRoleとUserのRole割当をread-onlyで取得するquery repositoryを提供する."""

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
    """短命なSQLAlchemy read sessionでRole read modelを取得する.

    Attributes:
        _session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread sessionのfactory.
    """

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """読み取り用session factoryを保持してrepositoryを初期化する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): query用の非同期read session factory.

        Returns:
            None: 読み取り用session factoryを保持したrepository instanceを初期化する.

        Notes:
            初期化時にはsessionを生成せず、Role assignment stateは変更しない.
        """
        self._session_factory = session_factory

    async def get_by_id(self, role_id: int) -> Role | None:
        """Role IDに一致するdomain Roleを取得する.

        Args:
            role_id (int): 取得対象Roleの永続ID.

        Returns:
            Role | None: domain Role. 対象rowが存在しない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
        """
        async with self._session_factory() as session:
            model = await session.get(RoleModel, role_id)
            return role_to_domain(model) if isinstance(model, RoleModel) else None

    async def get_by_name(self, name: str) -> Role | None:
        """Role名に一致するdomain Roleを取得する.

        Args:
            name (str): 完全一致で検索するRole名.

        Returns:
            Role | None: domain Role. 対象rowが存在しない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.

        Notes:
            Role名の正規化は行わない.
        """
        async with self._session_factory() as session:
            model = (
                await session.execute(select(RoleModel).where(RoleModel.name == name))
            ).scalar_one_or_none()
            return role_to_domain(model) if isinstance(model, RoleModel) else None

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        """Userに割り当てられたRoleをposition昇順で取得する.

        Args:
            user_id (int): Role assignmentを検索するUser ID.

        Returns:
            list[Role]: position昇順のdomain Role. 割当がない場合は空list.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
        """
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
        """名前がDefaultのRoleを取得する.

        Returns:
            Role: nameが正確にDefaultであるdomain Role.

        Raises:
            LookupError: nameがDefaultのRoleが永続化されていない場合.
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.

        Notes:
            Default Roleが必ず存在することはidentity bootstrapの不変条件である.
        """
        role = await self.get_by_name("Default")
        if role is None:
            msg = "No role named 'Default' exists"
            raise LookupError(msg)
        return role

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        """Roleが割り当てられたUser IDを昇順で取得する.

        Args:
            role_id (int): assignmentを検索するRoleの永続ID.

        Returns:
            list[int]: User IDの昇順list. 割当がない場合は空list.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
        """
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(UserRoleModel.user_id)
                    .where(UserRoleModel.role_id == role_id)
                    .order_by(UserRoleModel.user_id.asc())
                )
            ).all()
            return [row[0] for row in rows]
