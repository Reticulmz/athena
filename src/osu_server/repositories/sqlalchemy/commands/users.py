"""SQLAlchemyでidentity userと禁止usernameを永続化するrepositoryを提供する."""

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
    """Unit of Work所有sessionでidentity userを操作するrepository.

    Attributes:
        _session (AsyncSession): command transactionを実行しcommitを所有しないsession.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Workから受け取ったSQLAlchemy sessionを保持する.

        Args:
            session (AsyncSession): identity user操作に使うsession.

        Notes:
            commitとrollbackは呼び出し側のUnit of Workが所有する.
        """
        self._session: AsyncSession = session

    async def create(self, user: User) -> User:
        """usernameとemailが重複しないuserを新規作成する.

        Args:
            user (User): usernameとemailと認証情報を持つ新規user.

        Returns:
            User: lowercase正規化後に永続化されたuser.

        Raises:
            ValueError: safe_usernameまたはemailが既に存在する場合.
            SQLAlchemyError: 重複以外の永続化処理に失敗した場合.

        Notes:
            safe_usernameとemailはlowercaseで照合して保存する.
        """
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
        """Safe usernameをlowercase正規化してuserを取得する.

        Args:
            safe_username (str): 取得対象userのsafe username.

        Returns:
            User | None: 対応するuser. 存在しない場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        model = (
            await self._session.execute(
                select(UserModel).where(UserModel.safe_username == safe_username.lower())
            )
        ).scalar_one_or_none()
        return _user_to_domain(model) if isinstance(model, UserModel) else None

    async def get_by_email(self, email: str) -> User | None:
        """emailをlowercase正規化してuserを取得する.

        Args:
            email (str): 取得対象userのemail address.

        Returns:
            User | None: 対応するuser. 存在しない場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        model = (
            await self._session.execute(select(UserModel).where(UserModel.email == email.lower()))
        ).scalar_one_or_none()
        return _user_to_domain(model) if isinstance(model, UserModel) else None

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """Safe usernameが登録禁止かをlowercase正規化して確認する.

        Args:
            safe_username (str): 確認対象のsafe username.

        Returns:
            bool: 禁止usernameとして保存済みの場合はTrue. 未登録の場合はFalse.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        model = (
            await self._session.execute(
                select(DisallowedUsernameModel).where(
                    DisallowedUsernameModel.safe_username == safe_username.lower()
                )
            )
        ).scalar_one_or_none()
        return model is not None

    async def add_disallowed_username(self, safe_username: str) -> None:
        """Safe usernameを未登録の場合だけ禁止usernameへ追加する.

        Args:
            safe_username (str): 登録禁止にするsafe username.

        Returns:
            None: 禁止usernameが保存済みであることを確認したことを示す.

        Raises:
            SQLAlchemyError: 既存確認またはflushに失敗した場合.

        Notes:
            lowercaseで照合し同じusernameが既にある場合はno-opとする.
        """
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
        """指定userが存在する場合だけcountry codeを更新する.

        Args:
            user_id (int): 更新対象userの永続化識別子.
            country (str): 保存するcountry code.

        Returns:
            None: 更新または存在しないuserのno-op完了を示す.

        Raises:
            SQLAlchemyError: selectまたはflushに失敗した場合.

        Notes:
            存在しないuserは例外にせずno-opとする.
        """
        model = await self._session.get(UserModel, user_id)
        if isinstance(model, UserModel):
            model.country = country
            await self._session.flush()

    async def update_password_hash(self, user_id: int, password_hash: str) -> bool:
        """指定userが存在する場合だけpassword hashを更新する.

        Args:
            user_id (int): 更新対象userの永続化識別子.
            password_hash (str): 保存する認証用password hash.

        Returns:
            bool: userが存在し更新した場合はTrue. 存在しない場合はFalse.

        Raises:
            SQLAlchemyError: selectまたはflushに失敗した場合.
        """
        model = await self._session.get(UserModel, user_id)
        if not isinstance(model, UserModel):
            return False
        model.password_hash = password_hash
        await self._session.flush()
        return True

    async def touch_latest_activity(self, user_id: int, occurred_at: datetime) -> bool:
        """指定userが存在する場合だけlatest activity timestampを更新する.

        Args:
            user_id (int): 更新対象userの永続化識別子.
            occurred_at (datetime): replay download activityが発生した時刻.

        Returns:
            bool: userが存在し更新した場合はTrue. 存在しない場合はFalse.

        Raises:
            SQLAlchemyError: selectまたはflushに失敗した場合.

        Notes:
            updated_atをactivity metadataとして扱わない.
        """
        model = await self._session.get(UserModel, user_id)
        if not isinstance(model, UserModel):
            return False
        model.latest_activity_at = occurred_at
        await self._session.flush()
        return True

    async def sync_system_user(self, identity: SystemUserIdentity) -> None:
        """固定idのsystem userと関連する禁止usernameを同期する.

        Args:
            identity (SystemUserIdentity): 保存するsystem userの表示username.

        Returns:
            None: system userと禁止usernameのflush完了を示す.

        Raises:
            ValueError: system user以外が同じsafe usernameを使っている場合.
            SQLAlchemyError: upsertまたは禁止username追加の実行に失敗した場合.

        Notes:
            system user idは1に固定しbanchobotと正規化usernameを禁止usernameへ追加する.
        """
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
    """user保存時のunique constraint違反を利用者向けValueErrorへ変換する.

    Args:
        user (User): 重複を検出した作成対象user.
        exc (IntegrityError): databaseから送出されたunique constraint違反候補.

    Returns:
        ValueError: safe_usernameかemailまたは一般的なunique constraint failureを説明する例外.

    Notes:
        このhelperは例外を返すだけで送出しない.
    """
    constraint_name = _constraint_name(exc)
    text = str(getattr(exc, "orig", exc))
    if constraint_name == "users_safe_username_key" or "users_safe_username_key" in text:
        return ValueError(f"safe_username already exists: {user.safe_username}")
    if constraint_name == "users_email_key" or "users_email_key" in text:
        return ValueError(f"email already exists: {user.email}")
    return ValueError("user uniqueness constraint failed")


def _constraint_name(exc: IntegrityError) -> str | None:
    """Database driver例外からconstraint nameを安全に取り出す.

    Args:
        exc (IntegrityError): origまたはorig.diagにdriver詳細を持つ可能性がある例外.

    Returns:
        str | None: 取得できたconstraint name. driverが公開しない場合はNone.
    """
    orig = exc.orig
    direct = getattr(orig, "constraint_name", None)
    if isinstance(direct, str):
        return direct
    diag = getattr(orig, "diag", None)
    from_diag = getattr(diag, "constraint_name", None)
    return from_diag if isinstance(from_diag, str) else None


def _user_to_domain(model: UserModel) -> User:
    """SQLAlchemy user modelをidentity domain modelへ変換する.

    Args:
        model (UserModel): 永続化層から読み出したuser row.

    Returns:
        User: usernameと認証情報とactivity timestampを持つdomain user.
    """
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
