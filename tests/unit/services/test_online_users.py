"""Tests for OnlineUsersService.

Validates:
- Req 6.3: OnlineUsersService delegates get_all_user_ids() to SessionStore
- Constructor accepts SessionStore dependency
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.online_users import OnlineUsersService

if TYPE_CHECKING:
    from osu_server.domain.session import SessionData

# ── Fake SessionStore ───────────────────────────────────────────────


class FakeSessionStore:
    """テスト用の SessionStore 実装。"""

    def __init__(self, user_ids: list[int] | None = None) -> None:
        self._user_ids = user_ids or []

    async def create(self, _user_id: int, _token: str, _data: SessionData) -> None:
        pass

    async def get(self, _token: str) -> SessionData | None:
        return None

    async def get_by_user(self, _user_id: int) -> SessionData | None:
        return None

    async def delete(self, _token: str) -> None:
        pass

    async def exists(self, _token: str) -> bool:
        return False

    async def refresh(self, _token: str) -> bool:
        return False

    async def delete_by_user(self, _user_id: int) -> None:
        pass

    async def get_all_user_ids(self) -> list[int]:
        return self._user_ids


class TestOnlineUsersServiceProtocol:
    """OnlineUsersService は SessionStore を受け取る。"""

    def test_accepts_session_store(self) -> None:
        store = FakeSessionStore()
        svc = OnlineUsersService(session_store=store)
        assert svc is not None

    def test_fake_satisfies_protocol(self) -> None:
        store = FakeSessionStore()
        assert isinstance(store, SessionStore)


class TestGetAllUserIds:
    """Req 6.3: get_all_user_ids() は SessionStore に委譲する。"""

    async def test_returns_empty_list_when_no_sessions(self) -> None:
        store = FakeSessionStore(user_ids=[])
        svc = OnlineUsersService(session_store=store)

        result = await svc.get_all_user_ids()

        assert result == []

    async def test_returns_user_ids_from_store(self) -> None:
        store = FakeSessionStore(user_ids=[1, 2, 3])
        svc = OnlineUsersService(session_store=store)

        result = await svc.get_all_user_ids()

        assert result == [1, 2, 3]

    async def test_delegates_to_session_store(self) -> None:
        """戻り値が SessionStore.get_all_user_ids() の結果と同一であること。"""
        expected = [10, 20, 30]
        store = FakeSessionStore(user_ids=expected)
        svc = OnlineUsersService(session_store=store)

        result = await svc.get_all_user_ids()

        assert result is expected
