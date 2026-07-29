"""SQLAlchemyからfriend relationshipをread-onlyで取得するquery repositoryを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osu_server.repositories.sqlalchemy.models.friend import UserFriendRelationshipModel

if TYPE_CHECKING:
    from osu_server.repositories.sqlalchemy.queries._shared import (
        SQLAlchemyQuerySessionFactory,
    )


class SQLAlchemyFriendRelationshipQueryRepository:
    """短命なSQLAlchemy read sessionでfriend relationshipを取得する.

    Attributes:
        _session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread sessionのfactory.
    """

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """読み取り用session factoryを保持してrepositoryを初期化する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): query用の非同期read session factory.

        Notes:
            初期化時にはsessionを生成せず,relationship stateは変更しない.
        """
        self._session_factory: SQLAlchemyQuerySessionFactory = session_factory

    async def list_friend_ids(self, owner_user_id: int) -> tuple[int, ...]:
        """所有Userが登録したfriend User IDを作成順で取得する.

        Args:
            owner_user_id (int): friend relationshipの所有者となるUser ID.

        Returns:
            tuple[int, ...]: created_atとtarget User IDで昇順に並ぶfriend User ID.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.

        Notes:
            relationshipが存在しない場合は空tupleを返す.
        """
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(UserFriendRelationshipModel.target_user_id)
                    .where(UserFriendRelationshipModel.owner_user_id == owner_user_id)
                    .order_by(
                        UserFriendRelationshipModel.created_at,
                        UserFriendRelationshipModel.target_user_id,
                    )
                )
            ).scalars()
            return tuple(rows.all())

    async def has_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        """指定した有向friend relationshipが存在するかを返す.

        Args:
            owner_user_id (int): relationshipの所有者となるUser ID.
            target_user_id (int): 所有者がfriendとして登録したか確認するUser ID.

        Returns:
            bool: 完全一致するrelationshipが1件以上あればTrue. それ以外はFalse.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.

        Notes:
            逆方向のrelationshipはこの確認の対象にしない.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(UserFriendRelationshipModel.target_user_id)
                .where(
                    UserFriendRelationshipModel.owner_user_id == owner_user_id,
                    UserFriendRelationshipModel.target_user_id == target_user_id,
                )
                .limit(1)
            )
            return result.scalar_one_or_none() is not None
