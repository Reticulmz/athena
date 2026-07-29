"""SQLAlchemyからUserとdisallowed usernameをread-onlyで取得するquery repositoryを提供する."""

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
    """短命なSQLAlchemy read sessionでUser read modelを取得する.

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
            初期化時にはsessionを生成せず,User stateは変更しない.
        """
        self._session_factory = session_factory

    async def get_by_id(self, user_id: int) -> User | None:
        """User IDに一致するdomain Userを取得する.

        Args:
            user_id (int): 取得対象Userの永続ID.

        Returns:
            User | None: domain User. 対象rowが存在しない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
        """
        async with self._session_factory() as session:
            model = await session.get(UserModel, user_id)
            return user_to_domain(model) if isinstance(model, UserModel) else None

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Safe usernameに一致するdomain Userを取得する.

        Args:
            safe_username (str): 大文字小文字を区別せず検索するsafe username.

        Returns:
            User | None: domain User. 対象rowが存在しない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.

        Notes:
            検索前にstr.lower()だけを適用し,空白除去やUnicode正規化は行わない.
        """
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(UserModel).where(UserModel.safe_username == safe_username.lower())
                )
            ).scalar_one_or_none()
            return user_to_domain(model) if isinstance(model, UserModel) else None

    async def get_by_email(self, email: str) -> User | None:
        """emailに一致するdomain Userを取得する.

        Args:
            email (str): 大文字小文字を区別せず検索するemail address.

        Returns:
            User | None: domain User. 対象rowが存在しない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.

        Notes:
            検索前にstr.lower()だけを適用し,空白除去やemail validationは行わない.
        """
        async with self._session_factory() as session:
            model = (
                await session.execute(select(UserModel).where(UserModel.email == email.lower()))
            ).scalar_one_or_none()
            return user_to_domain(model) if isinstance(model, UserModel) else None

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """Safe usernameが禁止一覧に存在するかを返す.

        Args:
            safe_username (str): 大文字小文字を区別せず検索するsafe username.

        Returns:
            bool: 禁止一覧に完全一致するrowがあればTrue. それ以外はFalse.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.

        Notes:
            検索前にstr.lower()だけを適用し,禁止一覧は変更しない.
        """
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(DisallowedUsernameModel).where(
                        DisallowedUsernameModel.safe_username == safe_username.lower()
                    )
                )
            ).scalar_one_or_none()
            return model is not None
