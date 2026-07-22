"""SQLAlchemyでuser間friend relationshipを永続化するrepositoryを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from osu_server.domain.identity.friends import FriendRelationship
from osu_server.repositories.sqlalchemy.models.friend import UserFriendRelationshipModel
from osu_server.repositories.sqlalchemy.models.user import UserModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyFriendRelationshipCommandRepository:
    """Unit of Work所有sessionでfriend relationshipを変更するrepository.

    Attributes:
        _session (AsyncSession): command transactionを実行しcommitを所有しないsession.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Workから受け取ったSQLAlchemy sessionを保持する.

        Args:
            session (AsyncSession): friend relationship操作に使うsession.

        Returns:
            None: repositoryの初期化完了を示す.

        Notes:
            commitとrollbackは呼び出し側のUnit of Workが所有する.
        """
        self._session: AsyncSession = session

    async def target_exists(self, user_id: int) -> bool:
        """friend登録対象となるuserの存在を確認する.

        Args:
            user_id (int): 確認するuserの永続化識別子.

        Returns:
            bool: userが存在する場合はTrue. 存在しない場合はFalse.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        result = await self._session.execute(
            select(UserModel.id).where(UserModel.id == user_id).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def add_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        """ownerからtargetへのfriend relationshipを重複なく追加する.

        Args:
            owner_user_id (int): relationshipを所有するuserの永続化識別子.
            target_user_id (int): friendとして登録するuserの永続化識別子.

        Returns:
            bool: 新しいrelationshipを追加した場合はTrue. 既存の場合はFalse.

        Raises:
            SQLAlchemyError: insert実行に失敗した場合.

        Notes:
            databaseのconflict処理により同一組は重複保存しない.
        """
        relationship = FriendRelationship(
            owner_user_id=owner_user_id,
            target_user_id=target_user_id,
        )
        statement = insert(UserFriendRelationshipModel).values(
            owner_user_id=relationship.owner_user_id,
            target_user_id=relationship.target_user_id,
        )
        result = await self._session.execute(
            statement.on_conflict_do_nothing(
                index_elements=[
                    UserFriendRelationshipModel.owner_user_id,
                    UserFriendRelationshipModel.target_user_id,
                ]
            ).returning(UserFriendRelationshipModel.target_user_id)
        )
        return result.scalar_one_or_none() is not None

    async def remove_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        """ownerからtargetへのfriend relationshipを削除する.

        Args:
            owner_user_id (int): relationshipを所有するuserの永続化識別子.
            target_user_id (int): 削除するfriendの永続化識別子.

        Returns:
            bool: 保存済みrelationshipを削除した場合はTrue. 未登録の場合はFalse.

        Raises:
            SQLAlchemyError: delete実行に失敗した場合.
        """
        result = await self._session.execute(
            delete(UserFriendRelationshipModel)
            .where(
                UserFriendRelationshipModel.owner_user_id == owner_user_id,
                UserFriendRelationshipModel.target_user_id == target_user_id,
            )
            .returning(UserFriendRelationshipModel.target_user_id)
        )
        return result.scalar_one_or_none() is not None
