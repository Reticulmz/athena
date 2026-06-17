"""SQLAlchemy command-side friend relationship repository."""

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
    """Friend command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def target_exists(self, user_id: int) -> bool:
        result = await self._session.execute(
            select(UserModel.id).where(UserModel.id == user_id).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def add_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
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
        result = await self._session.execute(
            delete(UserFriendRelationshipModel)
            .where(
                UserFriendRelationshipModel.owner_user_id == owner_user_id,
                UserFriendRelationshipModel.target_user_id == target_user_id,
            )
            .returning(UserFriendRelationshipModel.target_user_id)
        )
        return result.scalar_one_or_none() is not None
