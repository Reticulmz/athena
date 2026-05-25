"""OnlineUsersService — オンラインユーザー一覧の取得。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.session_store import SessionStore


class OnlineUsersService:
    """SessionStore に委譲してオンラインユーザー ID を返すサービス。"""

    _session_store: SessionStore

    def __init__(self, session_store: SessionStore) -> None:
        self._session_store = session_store

    async def get_all_user_ids(self) -> list[int]:
        """全オンラインユーザーの ID リストを返す。"""
        return await self._session_store.get_all_user_ids()
