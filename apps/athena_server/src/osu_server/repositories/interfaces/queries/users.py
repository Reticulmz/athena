"""Display と lookup workflow 用 user read-only repository contract を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.users import User


class UserQueryRepository(Protocol):
    """Display と lookup workflow 用 user read-only access を定義する.

    Notes:
        この Protocol は User と username reservation の read model を返すだけである. User state を
        変更せず Command Unit of Work を開始または commit/rollback しない.
    """

    async def get_by_id(self, user_id: int) -> User | None:
        """Identifier に対応する User を返す.

        Args:
            user_id (int): 検索する User ID.

        Returns:
            User | None: 対応する User. 見つからない場合は `None`.
        """
        ...

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Normalized username に対応する User を返す.

        Args:
            safe_username (str): 検索する normalized username.

        Returns:
            User | None: 対応する User. 見つからない場合は `None`.
        """
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Email address に対応する User を返す.

        Args:
            email (str): 検索する email address.

        Returns:
            User | None: 対応する User. 見つからない場合は `None`.
        """
        ...

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """Normalized username が reservation 済みかを返す.

        Args:
            safe_username (str): 確認する normalized username.

        Returns:
            bool: Username が registration 不可の場合は `True`. それ以外は `False`.
        """
        ...
