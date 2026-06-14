"""SQLAlchemy query-side user repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osu_server.repositories.sqlalchemy.models.user import DisallowedUsernameModel, UserModel
from osu_server.repositories.sqlalchemy.queries._shared import (
    SQLAlchemyQuerySessionFactory,
    user_to_domain,
)

if TYPE_CHECKING:
    from osu_server.domain.identity.users import User


class SQLAlchemyUserQueryRepository:
    """Read-only user repository backed by short SQLAlchemy sessions."""

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        self._session_factory = session_factory

    async def get_by_id(self, user_id: int) -> User | None:
        async with self._session_factory() as session:
            model = await session.get(UserModel, user_id)
            return user_to_domain(model) if isinstance(model, UserModel) else None

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(UserModel).where(UserModel.safe_username == safe_username.lower())
                )
            ).scalar_one_or_none()
            return user_to_domain(model) if isinstance(model, UserModel) else None

    async def get_by_email(self, email: str) -> User | None:
        async with self._session_factory() as session:
            model = (
                await session.execute(select(UserModel).where(UserModel.email == email.lower()))
            ).scalar_one_or_none()
            return user_to_domain(model) if isinstance(model, UserModel) else None

    async def is_username_disallowed(self, safe_username: str) -> bool:
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(DisallowedUsernameModel).where(
                        DisallowedUsernameModel.safe_username == safe_username.lower()
                    )
                )
            ).scalar_one_or_none()
            return model is not None
