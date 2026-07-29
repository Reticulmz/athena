"""User mutation workflow の command-side repository 契約."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.identity.system_users import SystemUserIdentity
    from osu_server.domain.identity.users import User


@runtime_checkable
class UserCommandRepository(Protocol):
    """User の mutation と consistency-check port.

    Notes:
        Runtime 実装は command Unit of Work から取得する.各操作は同じ Unit of Work が
        所有する transaction に参加し,この repository 自身は commit または rollback を
        実行しない.
    """

    async def create(self, user: User) -> User:
        """新しい User を永続化し repository-assigned identity 付きで返す.

        Args:
            user (User): 永続化する未保存 User.

        Returns:
            User: Repository-assigned identity を含む永続化後の User.

        Raises:
            ValueError: normalized username または email address が既存 User と重複する場合に
                送出する.
        """
        ...

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Uniqueness check 用に normalized username から User を返す.

        Args:
            safe_username (str): 検索する normalized username.

        Returns:
            User | None: 一致する User.存在しない場合は None.
        """
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Uniqueness check 用に email address から User を返す.

        Args:
            email (str): 検索する email address.

        Returns:
            User | None: 一致する User.存在しない場合は None.
        """
        ...

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """Normalized username が予約済みか返す.

        Args:
            safe_username (str): 確認する normalized username.

        Returns:
            bool: Username が予約済みの場合は True.予約されていない場合は False.
        """
        ...

    async def add_disallowed_username(self, safe_username: str) -> None:
        """Normalized username を予約する.

        Args:
            safe_username (str): 予約する normalized username.

        Returns:
            None: Username の予約が Unit of Work に反映されたことを示す.
        """
        ...

    async def update_country(self, user_id: int, country: str) -> None:
        """User の country code を永続化する.

        Args:
            user_id (int): 更新する User ID.
            country (str): 保存する country code.

        Returns:
            None: Country code が Unit of Work に反映されたことを示す.
        """
        ...

    async def update_password_hash(self, user_id: int, password_hash: str) -> bool:
        """User の password hash を永続化し対象が存在したか返す.

        Args:
            user_id (int): 更新する User ID.
            password_hash (str): 保存する password hash.

        Returns:
            bool: 対象 User を更新した場合は True.存在しない場合は False.
        """
        ...

    async def touch_latest_activity(self, user_id: int, occurred_at: datetime) -> bool:
        """対象 user の latest activity を更新し,存在したか返す.

        Args:
            user_id (int): 更新する user の識別子.
            occurred_at (datetime): activity が発生した日時.

        Returns:
            bool: 対象 user を更新した場合は True.存在しない場合は False.
        """
        ...

    async def sync_system_user(self, identity: SystemUserIdentity) -> None:
        """設定済み system User record と username reservation の存在を保証する.

        Args:
            identity (SystemUserIdentity): 同期する system user の identity.

        Returns:
            None: System user record と reservation が Unit of Work に反映されたことを示す.

        Raises:
            ValueError: 設定済み system username が別の既存 User と競合する場合に送出する.
        """
        ...
