"""SQLAlchemy query-side friend relationship repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osu_server.repositories.sqlalchemy.models.friend import UserFriendRelationshipModel

if TYPE_CHECKING:
    from osu_server.repositories.sqlalchemy.queries._shared import (
        SQLAlchemyQuerySessionFactory,
    )


class SQLAlchemyFriendRelationshipQueryRepository:
    """Read-only friend relationship repository backed by short sessions."""

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        self._session_factory: SQLAlchemyQuerySessionFactory = session_factory

    async def list_friend_ids(self, owner_user_id: int) -> tuple[int, ...]:
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
