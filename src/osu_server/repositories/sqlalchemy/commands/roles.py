"""SQLAlchemyでroleとuser role assignmentを永続化するrepositoryを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyRoleCommandRepository:
    """Unit of Work所有sessionでrole assignmentを操作するrepository.

    Attributes:
        _session (AsyncSession): command transactionを実行しcommitを所有しないsession.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Workから受け取ったSQLAlchemy sessionを保持する.

        Args:
            session (AsyncSession): roleとassignment操作に使うsession.

        Notes:
            commitとrollbackは呼び出し側のUnit of Workが所有する.
        """
        self._session: AsyncSession = session

    async def get_by_id(self, role_id: int) -> Role | None:
        """永続化識別子でroleを取得する.

        Args:
            role_id (int): 取得対象roleの永続化識別子.

        Returns:
            Role | None: 対応するrole. 存在しない場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        model = await self._session.get(RoleModel, role_id)
        return _role_to_domain(model) if isinstance(model, RoleModel) else None

    async def get_by_name(self, name: str) -> Role | None:
        """完全一致nameでroleを取得する.

        Args:
            name (str): 取得対象roleの完全一致name.

        Returns:
            Role | None: 対応するrole. 存在しない場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        model = (
            await self._session.execute(select(RoleModel).where(RoleModel.name == name))
        ).scalar_one_or_none()
        return _role_to_domain(model) if isinstance(model, RoleModel) else None

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        """userへ割り当て済みroleをposition順で取得する.

        Args:
            user_id (int): roleを取得するuserの永続化識別子.

        Returns:
            list[Role]: position昇順のrole list. 未割当時は空list.

        Raises:
            SQLAlchemyError: join selectの実行に失敗した場合.
        """
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
        """userへroleを未割当の場合だけ追加する.

        Args:
            user_id (int): assignmentを受けるuserの永続化識別子.
            role_id (int): assignmentするroleの永続化識別子.

        Returns:
            None: assignmentが存在する状態を確認したことを示す.

        Raises:
            SQLAlchemyError: 既存確認またはflushに失敗した場合.

        Notes:
            同じuserとroleの組が既にある場合はno-opとする.
        """
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

    async def set_roles_for_user(self, user_id: int, role_ids: tuple[int, ...]) -> None:
        """userのrole assignmentを指定した識別子集合で置き換える.

        Args:
            user_id (int): assignmentを置換するuserの永続化識別子.
            role_ids (tuple[int, ...]): 保存するroleの永続化識別子. 重複は除外する.

        Returns:
            None: 既存assignmentの削除と新assignmentのflush完了を示す.

        Raises:
            SQLAlchemyError: deleteまたはflushに失敗した場合.

        Notes:
            空tupleは全assignmentを削除する.
        """
        _ = await self._session.execute(
            delete(UserRoleModel).where(UserRoleModel.user_id == user_id)
        )
        self._session.add_all(
            UserRoleModel(user_id=user_id, role_id=role_id) for role_id in dict.fromkeys(role_ids)
        )
        await self._session.flush()

    async def get_default_role(self) -> Role:
        """nameがDefaultのroleを取得する.

        Returns:
            Role: nameがDefaultの保存済みrole.

        Raises:
            LookupError: nameがDefaultのroleが存在しない場合.
            SQLAlchemyError: select実行に失敗した場合.
        """
        role = await self.get_by_name("Default")
        if role is None:
            msg = "No role named 'Default' exists"
            raise LookupError(msg)
        return role

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        """指定roleを割り当て済みのuser idを昇順で取得する.

        Args:
            role_id (int): assignmentを検索するroleの永続化識別子.

        Returns:
            list[int]: user idの昇順list. 割当がない場合は空list.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        rows = (
            await self._session.execute(
                select(UserRoleModel.user_id)
                .where(UserRoleModel.role_id == role_id)
                .order_by(UserRoleModel.user_id.asc())
            )
        ).all()
        return [row[0] for row in rows]


def _role_to_domain(model: RoleModel) -> Role:
    """SQLAlchemy role modelをidentity domain modelへ変換する.

    Args:
        model (RoleModel): 永続化層から読み出したrole row.

    Returns:
        Role: permissionsをPrivilegesへ復元したrole.

    Notes:
        PrivilegesはIntFlagとして任意の整数bitmaskを保持するため変換時にValueErrorを送出しない.
    """
    return Role(
        id=model.id,
        name=model.name,
        permissions=Privileges(model.permissions),
        position=model.position,
    )
