"""Tests for SessionAuthorizationService.refresh_user_authorization."""

from __future__ import annotations

import pytest

from osu_server.domain.role import Privileges
from osu_server.domain.session_authorization import (
    AuthorizationRefreshStatus,
    SessionAuthorization,
)
from osu_server.services.session_authorization_service import (
    SessionAuthorizationService,
)

# ── Fakes ──────────────────────────────────────────────────────────────


class FakePermissionService:
    """compute_session_authorization の戻り値を制御する fake。"""

    snapshot: SessionAuthorization
    _should_fail: bool

    def __init__(
        self,
        snapshot: SessionAuthorization | None = None,
        *,
        should_fail: bool = False,
    ) -> None:
        self.snapshot = snapshot or SessionAuthorization(
            privileges=Privileges.NORMAL,
            role_ids=(1,),
        )
        self._should_fail = should_fail
        self.compute_calls: list[int] = []

    async def compute_session_authorization(
        self,
        user_id: int,
    ) -> SessionAuthorization:
        self.compute_calls.append(user_id)
        if self._should_fail:
            raise RuntimeError("compute failed")
        return self.snapshot


class FakeSessionStore:
    """update_authorization の戻り値を制御する fake。全 Protocol メソッドを実装。"""

    _update_result: bool
    _by_token: dict[str, object]
    _by_user: dict[int, object]

    def __init__(self, *, update_result: bool = True) -> None:
        self._update_result = update_result
        self._by_token = {}
        self._by_user = {}
        self.update_calls: list[tuple[int, SessionAuthorization]] = []

    async def create(self, user_id: int, token: str, data: object) -> None:
        _ = (user_id, token, data)

    async def get(self, token: str) -> object | None:
        _ = token
        return None

    async def get_by_user(self, user_id: int) -> object | None:
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
        return []

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        self.update_calls.append((user_id, authorization))
        return self._update_result


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def perm_svc() -> FakePermissionService:
    return FakePermissionService()


@pytest.fixture
def session_store() -> FakeSessionStore:
    return FakeSessionStore()


def _make_service(
    perm_svc: FakePermissionService,
    session_store: FakeSessionStore,
) -> SessionAuthorizationService:
    return SessionAuthorizationService(
        permission_service=perm_svc,  # pyright: ignore[reportArgumentType]
        session_store=session_store,  # pyright: ignore[reportArgumentType]
    )


# ── refresh_user_authorization ─────────────────────────────────────────


class TestRefreshUserAuthorizationRefreshed:
    """active session がある場合、REFRESHED と新しい snapshot を返す。"""

    async def test_returns_refreshed_status(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        svc = _make_service(perm_svc, session_store)

        result = await svc.refresh_user_authorization(user_id=1)

        assert result.status == AuthorizationRefreshStatus.REFRESHED

    async def test_returns_new_authorization_snapshot(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        new_snapshot = SessionAuthorization(
            privileges=Privileges.ADMIN,
            role_ids=(5, 6),
        )
        perm_svc.snapshot = new_snapshot
        svc = _make_service(perm_svc, session_store)

        result = await svc.refresh_user_authorization(user_id=1)

        assert result.authorization == new_snapshot

    async def test_user_id_in_result(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        svc = _make_service(perm_svc, session_store)

        result = await svc.refresh_user_authorization(user_id=42)

        assert result.user_id == 42

    async def test_calls_compute_session_authorization(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        svc = _make_service(perm_svc, session_store)

        _ = await svc.refresh_user_authorization(user_id=7)

        assert perm_svc.compute_calls == [7]

    async def test_calls_update_authorization_with_snapshot(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        svc = _make_service(perm_svc, session_store)

        _ = await svc.refresh_user_authorization(user_id=3)

        assert len(session_store.update_calls) == 1
        call_user_id, call_auth = session_store.update_calls[0]
        assert call_user_id == 3
        assert call_auth == perm_svc.snapshot


class TestRefreshUserAuthorizationNoActiveSession:
    """active session がない場合、NO_ACTIVE_SESSION を返し session を作成しない。"""

    async def test_returns_no_active_session(
        self,
        perm_svc: FakePermissionService,
    ) -> None:
        store = FakeSessionStore(update_result=False)
        svc = _make_service(perm_svc, store)

        result = await svc.refresh_user_authorization(user_id=1)

        assert result.status == AuthorizationRefreshStatus.NO_ACTIVE_SESSION

    async def test_authorization_is_none(
        self,
        perm_svc: FakePermissionService,
    ) -> None:
        store = FakeSessionStore(update_result=False)
        svc = _make_service(perm_svc, store)

        result = await svc.refresh_user_authorization(user_id=1)

        assert result.authorization is None

    async def test_still_attempts_update(
        self,
        perm_svc: FakePermissionService,
    ) -> None:
        store = FakeSessionStore(update_result=False)
        svc = _make_service(perm_svc, store)

        _ = await svc.refresh_user_authorization(user_id=1)

        # update_authorization was called; compute succeeded but store said no session
        assert len(store.update_calls) == 1


class TestRefreshUserAuthorizationFailed:
    """snapshot 計算が失敗した場合、FAILED を返し既存 session を維持する。"""

    async def test_returns_failed(
        self,
        session_store: FakeSessionStore,
    ) -> None:
        perm_svc = FakePermissionService(should_fail=True)
        svc = _make_service(perm_svc, session_store)

        result = await svc.refresh_user_authorization(user_id=1)

        assert result.status == AuthorizationRefreshStatus.FAILED

    async def test_authorization_is_none_on_failure(
        self,
        session_store: FakeSessionStore,
    ) -> None:
        perm_svc = FakePermissionService(should_fail=True)
        svc = _make_service(perm_svc, session_store)

        result = await svc.refresh_user_authorization(user_id=1)

        assert result.authorization is None

    async def test_does_not_call_update_on_failure(
        self,
        session_store: FakeSessionStore,
    ) -> None:
        perm_svc = FakePermissionService(should_fail=True)
        svc = _make_service(perm_svc, session_store)

        _ = await svc.refresh_user_authorization(user_id=1)

        assert len(session_store.update_calls) == 0
