"""SQLAlchemy command-side user repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from osu_server.domain.identity.users import User
from osu_server.repositories.sqlalchemy.models.user import (
    DisallowedUsernameModel,
    UserModel,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from osu_server.domain.identity.system_users import SystemUserIdentity

_BANCHO_BOT_USER_ID = 1


class SQLAlchemyUserCommandRepository:
    """User command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def create(self, user: User) -> User:
        safe_username = user.safe_username.lower()
        normalized_email = user.email.lower()
        existing_username = (
            await self._session.execute(
                select(UserModel).where(UserModel.safe_username == safe_username)
            )
        ).scalar_one_or_none()
        if existing_username is not None:
            msg = f"safe_username already exists: {user.safe_username}"
            raise ValueError(msg)

        existing_email = (
            await self._session.execute(
                select(UserModel).where(UserModel.email == normalized_email)
            )
        ).scalar_one_or_none()
        if existing_email is not None:
            msg = f"email already exists: {user.email}"
            raise ValueError(msg)

        model = UserModel(
            username=user.username,
            safe_username=safe_username,
            email=normalized_email,
            password_hash=user.password_hash,
            country=user.country,
            latest_activity_at=user.latest_activity_at,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise _user_uniqueness_error(user, exc) from exc
        await self._session.refresh(model)
        return _user_to_domain(model)

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        model = (
            await self._session.execute(
                select(UserModel).where(UserModel.safe_username == safe_username.lower())
            )
        ).scalar_one_or_none()
        return _user_to_domain(model) if isinstance(model, UserModel) else None

    async def get_by_email(self, email: str) -> User | None:
        model = (
            await self._session.execute(select(UserModel).where(UserModel.email == email.lower()))
        ).scalar_one_or_none()
        return _user_to_domain(model) if isinstance(model, UserModel) else None

    async def is_username_disallowed(self, safe_username: str) -> bool:
        model = (
            await self._session.execute(
                select(DisallowedUsernameModel).where(
                    DisallowedUsernameModel.safe_username == safe_username.lower()
                )
            )
        ).scalar_one_or_none()
        return model is not None

    async def add_disallowed_username(self, safe_username: str) -> None:
        existing = (
            await self._session.execute(
                select(DisallowedUsernameModel).where(
                    DisallowedUsernameModel.safe_username == safe_username.lower()
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        self._session.add(DisallowedUsernameModel(safe_username=safe_username.lower()))
        await self._session.flush()

    async def update_country(self, user_id: int, country: str) -> None:
        model = await self._session.get(UserModel, user_id)
        if isinstance(model, UserModel):
            model.country = country
            await self._session.flush()

    async def update_password_hash(self, user_id: int, password_hash: str) -> bool:
        model = await self._session.get(UserModel, user_id)
        if not isinstance(model, UserModel):
            return False
        model.password_hash = password_hash
        await self._session.flush()
        return True

    async def touch_latest_activity(self, user_id: int, occurred_at: datetime) -> bool:
        """対象 user の latest activity を更新する。

        引数:
            user_id: 更新対象 user の identifier.
            occurred_at: replay download activity が発生した時刻.

        戻り値:
            対象 user が存在し、更新された場合は True.

        例外:
            SQLAlchemy session の永続化例外は呼び出し元へ送出する.

        制約:
            updated_at は activity metadata として扱わない.
        """
        model = await self._session.get(UserModel, user_id)
        if not isinstance(model, UserModel):
            return False
        model.latest_activity_at = occurred_at
        await self._session.flush()
        return True

    async def sync_system_user(self, identity: SystemUserIdentity) -> None:
        safe_username = User.normalize_username(identity.username)
        conflict = (
            await self._session.execute(
                select(UserModel).where(
                    UserModel.safe_username == safe_username,
                    UserModel.id != _BANCHO_BOT_USER_ID,
                )
            )
        ).scalar_one_or_none()
        if conflict is not None:
            msg = f"configured system username conflicts with existing user: {safe_username}"
            raise ValueError(msg)

        stmt = (
            pg_insert(UserModel)
            .values(
                id=_BANCHO_BOT_USER_ID,
                username=identity.username,
                safe_username=safe_username,
                email="bot@internal",
                password_hash="!invalid",
                country="XX",
            )
            .on_conflict_do_update(
                index_elements=[UserModel.id],
                set_={
                    "username": identity.username,
                    "safe_username": safe_username,
                },
            )
        )
        _ = await self._session.execute(stmt)
        for name in ("banchobot", safe_username):
            stmt = (
                pg_insert(DisallowedUsernameModel)
                .values(safe_username=name)
                .on_conflict_do_nothing(
                    index_elements=[DisallowedUsernameModel.safe_username],
                )
            )
            _ = await self._session.execute(stmt)
        await self._session.flush()


def _user_uniqueness_error(user: User, exc: IntegrityError) -> ValueError:
    text = str(exc)
    if "safe_username" in text:
        return ValueError(f"safe_username already exists: {user.safe_username}")
    if "email" in text:
        return ValueError(f"email already exists: {user.email}")
    return ValueError("user uniqueness constraint failed")


def _user_to_domain(model: UserModel) -> User:
    return User(
        id=model.id,
        username=model.username,
        safe_username=model.safe_username,
        email=model.email,
        password_hash=model.password_hash,
        country=model.country,
        created_at=model.created_at,
        updated_at=model.updated_at,
        latest_activity_at=model.latest_activity_at,
    )
