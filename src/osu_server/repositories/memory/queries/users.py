"""Committed in-memory state から User を読む query adapter を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.identity.users import User
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryUserQueryRepository:
    """Committed in-memory state を読む read-only User repository.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): query ごとの committed snapshot を生成する factory.

    Notes:
        各 query は snapshot だけを読み, User state を変更しない.
    """

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Committed snapshot を取得する factory を保持する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): read に使用する committed state factory.
        """
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def get_by_id(self, user_id: int) -> User | None:
        """ID で User を取得する.

        Args:
            user_id (int): 取得する User の ID.

        Returns:
            User | None: snapshot 内の User. ID がなければ None.
        """
        state = self._factory.snapshot()
        return state.users_by_id.get(user_id)

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Lowercase 化した safe username の索引から User を取得する.

        Args:
            safe_username (str): 検索する safe username.

        Returns:
            User | None: 索引先の User. username または User がなければ None.

        Notes:
            入力は str.lower() してから検索する.
        """
        state = self._factory.snapshot()
        user_id = state.user_id_by_safe_username.get(safe_username.lower())
        if user_id is None:
            return None
        return state.users_by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Lowercase 化した email の索引から User を取得する.

        Args:
            email (str): 検索する email address.

        Returns:
            User | None: 索引先の User. email または User がなければ None.

        Notes:
            入力は str.lower() してから検索する.
        """
        state = self._factory.snapshot()
        user_id = state.user_id_by_email.get(email.lower())
        if user_id is None:
            return None
        return state.users_by_id.get(user_id)

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """Safe username が disallowed set に含まれるかを返す.

        Args:
            safe_username (str): 確認する safe username.

        Returns:
            bool: lowercase 化した username が disallowed set にあれば True, それ以外は False.

        Notes:
            入力は str.lower() してから検索する.
        """
        state = self._factory.snapshot()
        return safe_username.lower() in state.disallowed_usernames
