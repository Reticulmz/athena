"""SQLAlchemyUserRepository — async database-backed user repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: TC002

from osu_server.domain.identity.users import User
from osu_server.repositories.sqlalchemy.models.user import (
    DisallowedUsernameModel,
    UserModel,
)

if TYPE_CHECKING:
    from osu_server.domain.system_user import SystemUserIdentity

_BANCHO_BOT_USER_ID = 1


class SQLAlchemyUserRepository:
    """SQLAlchemy implementation of the UserRepository Protocol.

    Uses ``async_sessionmaker`` for database access.  Each method opens
    its own session to keep transactions short.
    """

    _session_factory: async_sessionmaker[AsyncSession]

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, user: User) -> User:
        """Persist a new user and return it with a generated id.

        Raises ``ValueError`` if ``safe_username`` or ``email`` already exists.
        """
        async with self._session_factory() as session:
            # Check for duplicate safe_username
            stmt = select(UserModel).where(UserModel.safe_username == user.safe_username)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                msg = f"safe_username already exists: {user.safe_username}"
                raise ValueError(msg)

            # Check for duplicate email (case-insensitive)
            normalized_email = user.email.lower()
            stmt = select(UserModel).where(UserModel.email == normalized_email)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                msg = f"email already exists: {user.email}"
                raise ValueError(msg)

            model = UserModel(
                username=user.username,
                safe_username=user.safe_username,
                email=normalized_email,
                password_hash=user.password_hash,
                country=user.country,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)

            return self._to_domain(model)

    async def get_by_id(self, user_id: int) -> User | None:
        """Return the user with *user_id*, or ``None`` if not found."""
        async with self._session_factory() as session:
            model = await session.get(UserModel, user_id)
            return self._to_domain(model) if model is not None else None

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Return the user with *safe_username*, or ``None`` if not found."""
        async with self._session_factory() as session:
            stmt = select(UserModel).where(UserModel.safe_username == safe_username.lower())
            model = (await session.execute(stmt)).scalar_one_or_none()
            return self._to_domain(model) if model is not None else None

    async def get_by_email(self, email: str) -> User | None:
        """Return the user with *email*, or ``None`` if not found."""
        async with self._session_factory() as session:
            stmt = select(UserModel).where(UserModel.email == email.lower())
            model = (await session.execute(stmt)).scalar_one_or_none()
            return self._to_domain(model) if model is not None else None

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """Return ``True`` if *safe_username* is in the disallowed list."""
        async with self._session_factory() as session:
            stmt = select(DisallowedUsernameModel).where(
                DisallowedUsernameModel.safe_username == safe_username.lower()
            )
            result = (await session.execute(stmt)).scalar_one_or_none()
            return result is not None

    async def add_disallowed_username(self, safe_username: str) -> None:
        """Add *safe_username* to the disallowed list.  Idempotent."""
        async with self._session_factory() as session:
            stmt = select(DisallowedUsernameModel).where(
                DisallowedUsernameModel.safe_username == safe_username.lower()
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                return

            model = DisallowedUsernameModel(safe_username=safe_username.lower())
            session.add(model)
            await session.commit()

    async def update_country(self, user_id: int, country: str) -> None:
        """Update the country code for *user_id*."""
        async with self._session_factory() as session:
            user = await session.get(UserModel, user_id)
            if user is not None:
                user.country = country
                await session.commit()

    async def sync_system_user(self, identity: SystemUserIdentity) -> None:
        safe = identity.username.lower().replace(" ", "_")
        async with self._session_factory() as session:
            stmt = select(UserModel).where(
                UserModel.safe_username == safe,
                UserModel.id != _BANCHO_BOT_USER_ID,
            )
            conflict = (await session.execute(stmt)).scalar_one_or_none()
            if conflict is not None:
                msg = f"configured BanchoBot safe username conflicts with existing user: {safe}"
                raise ValueError(msg)
            stmt = (
                pg_insert(UserModel)
                .values(
                    id=_BANCHO_BOT_USER_ID,
                    username=identity.username,
                    safe_username=safe,
                    email="bot@internal",
                    password_hash="!invalid",
                    country="XX",
                )
                .on_conflict_do_update(
                    index_elements=[UserModel.id],
                    set_={
                        "username": identity.username,
                        "safe_username": safe,
                    },
                )
            )
            _ = await session.execute(stmt)
            for name in ("banchobot", safe):
                stmt = (
                    pg_insert(DisallowedUsernameModel)
                    .values(
                        safe_username=name,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[DisallowedUsernameModel.safe_username],
                    )
                )
                _ = await session.execute(stmt)
            await session.commit()

    @staticmethod
    def _to_domain(model: UserModel) -> User:
        """Map a SQLAlchemy UserModel to a domain User."""
        return User(
            id=model.id,
            username=model.username,
            safe_username=model.safe_username,
            email=model.email,
            password_hash=model.password_hash,
            country=model.country,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
