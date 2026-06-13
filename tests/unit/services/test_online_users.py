"""Tests for OnlineUsersService.

Validates:
- Req 6.3: OnlineUsersService delegates get_all_user_ids() to SessionStore
- Req 3.3, 3.4: Only active session IDs returned; BanchoBot never implicitly added
- Constructor accepts SessionStore dependency
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.system_user import BANCHO_BOT_IDENTITY
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.online_users import OnlineUsersService

if TYPE_CHECKING:
    from osu_server.domain.identity.sessions import SessionData

# ── Fake SessionStore ───────────────────────────────────────────────


class FakeSessionStore:
    """テスト用の SessionStore 実装。"""

    _user_ids: list[int]

    def __init__(self, user_ids: list[int] | None = None) -> None:
        self._user_ids = user_ids or []

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        _ = (user_id, token, data)

    async def get(self, token: str) -> SessionData | None:
        _ = token
        return None

    async def get_by_user(self, user_id: int) -> SessionData | None:
        _ = user_id
        return None

    async def delete(self, token: str) -> None:
        _ = token

    async def exists(self, token: str) -> bool:
        _ = token
        return False

    async def refresh(self, token: str) -> bool:
        _ = token
        return False

    async def delete_by_user(self, user_id: int) -> None:
        _ = user_id

    async def get_all_user_ids(self) -> list[int]:
        return self._user_ids

    async def update_authorization(self, user_id: int, authorization: object) -> bool:
        _ = (user_id, authorization)
        raise NotImplementedError


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


class TestBanchoBotNotInActiveSessions:
    """Req 3.3, 3.4: get_all_user_ids() は active session IDs のみ返し、BanchoBot を含まない。

    OnlineUsersService は SessionStore に委譲するだけであり、BanchoBot を暗黙追加しない。
    BanchoBot は SessionData を持たず、active session ではないため、返却値に現れない。
    """

    async def test_banchobot_id_not_in_empty_result(self) -> None:
        """session store が空でも BanchoBot ID は追加されない。"""
        store = FakeSessionStore(user_ids=[])
        svc = OnlineUsersService(session_store=store)

        result = await svc.get_all_user_ids()

        assert result == []
        assert BANCHO_BOT_IDENTITY.user_id not in result

    async def test_banchobot_id_not_in_populated_result(self) -> None:
        """他のユーザーが online でも BanchoBot ID は返却値に含まれない。"""
        store = FakeSessionStore(user_ids=[2, 3, 42])
        svc = OnlineUsersService(session_store=store)

        result = await svc.get_all_user_ids()

        assert result == [2, 3, 42]
        assert BANCHO_BOT_IDENTITY.user_id not in result
        # BanchoBot が暗黙追加されていないことを長さでも検証
        assert len(result) == 3

    async def test_result_is_exact_pass_through_no_banchobot_appended(self) -> None:
        """get_all_user_ids() は SessionStore の結果をそのまま返し、BanchoBot を追記しない。"""
        session_ids = [100, 200, 300]
        store = FakeSessionStore(user_ids=session_ids)
        svc = OnlineUsersService(session_store=store)

        result = await svc.get_all_user_ids()

        assert BANCHO_BOT_IDENTITY.user_id not in result
        assert result == session_ids
        # pass-through: 厳密に SessionStore の返却値と同一オブジェクトであること
        assert result is session_ids

    async def test_banchobot_not_in_single_user_result(self) -> None:
        """1 ユーザーのみ online の場合も BanchoBot は追加されない。"""
        store = FakeSessionStore(user_ids=[55])
        svc = OnlineUsersService(session_store=store)

        result = await svc.get_all_user_ids()

        assert result == [55]
        assert BANCHO_BOT_IDENTITY.user_id not in result
        assert len(result) == 1
