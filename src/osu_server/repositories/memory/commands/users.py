"""In-memory command 側 user repository を実装する module."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from osu_server.domain.identity.users import User
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState, now_utc

if TYPE_CHECKING:
    from osu_server.domain.identity.system_users import SystemUserIdentity

_BANCHO_BOT_USER_ID = 1


class InMemoryUserCommandRepository:
    """User primary record, uniqueness index, disallowed username を command 用に管理する.

    Attributes:
        _state (InMemoryCommandRepositoryState): 所有 Unit of Work の可変 state snapshot.

    Notes:
        この repository は lock 又は thread synchronization を提供しない. 同じ state を
        複数 task 又は thread から同時に変更してはならない.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """Active Unit of Work の state snapshot を保持する.

        Args:
            state (InMemoryCommandRepositoryState): repository が直接読み書きする state.

        Returns:
            None: state への参照を保持したことを示す.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def create(self, user: User) -> User:
        """一意な safe username と email を持つ user を作成し ID を割り当てる.

        Args:
            user (User): 保存する user. 入力 ID は保存時に置き換える.

        Returns:
            User: BanchoBot の予約 ID を避けて next_user_id を割り当てた user.

        Raises:
            ValueError: lowercase safe username 又は lowercase email がすでに index に存在する場合.

        Notes:
            成功時は next_user_id, 主記録, safe username index, email index を更新する.
            next_user_id が BanchoBot の予約 ID ならその ID を飛ばす.
        """
        safe_username = user.safe_username.lower()
        email = user.email.lower()
        if safe_username in self._state.user_id_by_safe_username:
            msg = f"safe_username already exists: {user.safe_username}"
            raise ValueError(msg)
        if email in self._state.user_id_by_email:
            msg = f"email already exists: {user.email}"
            raise ValueError(msg)

        if self._state.next_user_id == _BANCHO_BOT_USER_ID:
            self._state.next_user_id += 1

        created = replace(user, id=self._state.next_user_id)
        self._state.next_user_id += 1
        self._state.users_by_id[created.id] = created
        self._state.user_id_by_safe_username[safe_username] = created.id
        self._state.user_id_by_email[email] = created.id
        return created

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Case-insensitive safe username から保存済み user を返す.

        Args:
            safe_username (str): 検索する safe username. lookup 前に lowercase 化する.

        Returns:
            User | None: index と主記録が存在する user. 未登録又は不整合時は None.
        """
        user_id = self._state.user_id_by_safe_username.get(safe_username.lower())
        if user_id is None:
            return None
        return self._state.users_by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Case-insensitive email から保存済み user を返す.

        Args:
            email (str): 検索する email. lookup 前に lowercase 化する.

        Returns:
            User | None: index と主記録が存在する user. 未登録又は不整合時は None.
        """
        user_id = self._state.user_id_by_email.get(email.lower())
        if user_id is None:
            return None
        return self._state.users_by_id.get(user_id)

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """Safe username が利用禁止 set に登録されているか返す.

        Args:
            safe_username (str): 判定する username. lookup 前に lowercase 化する.

        Returns:
            bool: disallowed username set に存在する場合は True.
        """
        return safe_username.lower() in self._state.disallowed_usernames

    async def add_disallowed_username(self, safe_username: str) -> None:
        """Safe username を利用禁止 set に追加する.

        Args:
            safe_username (str): 追加する username. 保存前に lowercase 化する.

        Returns:
            None: username を利用禁止 set に追加したことを示す.

        Notes:
            set を使用するため同じ username の追加は idempotent.
        """
        self._state.disallowed_usernames.add(safe_username.lower())

    async def update_country(self, user_id: int, country: str) -> None:
        """存在する user の country だけを置き換える.

        Args:
            user_id (int): 更新する user の識別子.
            country (str): 保存する country code.

        Returns:
            None: user が存在した場合は country を保存したことを示す.

        Notes:
            user_id が未登録の場合は state を変更せず例外も送出しない. updated_at は変更しない.
        """
        existing = self._state.users_by_id.get(user_id)
        if existing is not None:
            self._state.users_by_id[user_id] = replace(existing, country=country)

    async def update_password_hash(self, user_id: int, password_hash: str) -> bool:
        """存在する user の password hash と updated_at を更新する.

        Args:
            user_id (int): 更新する user の識別子.
            password_hash (str): 保存する password hash.

        Returns:
            bool: user を更新した場合は True. 未登録なら False.

        Notes:
            成功時の updated_at には現在 UTC 時刻を保存する. 未登録時は state を変更しない.
        """
        existing = self._state.users_by_id.get(user_id)
        if existing is None:
            return False
        self._state.users_by_id[user_id] = replace(
            existing,
            password_hash=password_hash,
            updated_at=now_utc(),
        )
        return True

    async def touch_latest_activity(self, user_id: int, occurred_at: datetime) -> bool:
        """存在する user の latest activity timestamp を更新する.

        Args:
            user_id (int): 更新する user の識別子.
            occurred_at (datetime): 保存する user-observable activity timestamp.

        Returns:
            bool: user を更新した場合は True. 未登録なら False.

        Notes:
            updated_at は変更しない. 未登録時は state を変更しない.
        """
        existing = self._state.users_by_id.get(user_id)
        if existing is None:
            return False
        self._state.users_by_id[user_id] = replace(
            existing,
            latest_activity_at=occurred_at,
        )
        return True

    async def sync_system_user(self, identity: SystemUserIdentity) -> None:
        """BanchoBot の予約 user record と利用禁止 usernames を同期する.

        Args:
            identity (SystemUserIdentity): 保存する system user identity.

        Returns:
            None: ID 1 の system user, indexes, 利用禁止 usernames を同期したことを示す.

        Raises:
            ValueError: 正規化した identity.username が ID 1 以外の既存 user と競合する場合.

        Notes:
            username は User.normalize_username で正規化する. 成功時は ID 1 の主記録を上書きし,
            bot@internal email index と banchobot 及び正規化 username の禁止登録を行う.
        """
        safe_username = User.normalize_username(identity.username)
        conflict_id = self._state.user_id_by_safe_username.get(safe_username)
        if conflict_id is not None and conflict_id != _BANCHO_BOT_USER_ID:
            msg = f"configured system username conflicts with existing user: {safe_username}"
            raise ValueError(msg)

        now = datetime.now(UTC)
        system_user = User(
            id=_BANCHO_BOT_USER_ID,
            username=identity.username,
            safe_username=safe_username,
            email="bot@internal",
            password_hash="!invalid",
            country="XX",
            created_at=now,
            updated_at=now,
        )
        self._state.users_by_id[_BANCHO_BOT_USER_ID] = system_user
        self._state.user_id_by_safe_username[safe_username] = _BANCHO_BOT_USER_ID
        self._state.user_id_by_email[system_user.email] = _BANCHO_BOT_USER_ID
        self._state.disallowed_usernames.add("banchobot")
        self._state.disallowed_usernames.add(safe_username)
