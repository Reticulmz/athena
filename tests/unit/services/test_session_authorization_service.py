"""Tests for SessionAuthorizationService.refresh_user_authorization."""

from __future__ import annotations

from typing import override

import pytest

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.sessions import (
    AuthorizationRefreshStatus,
    RoleAuthorizationRefreshResult,
    SessionAuthorization,
    SessionData,
)
from osu_server.services.commands.identity.session_authorization_service import (
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
    _by_token: dict[str, SessionData]
    _by_user: dict[int, SessionData]

    def __init__(self, *, update_result: bool = True) -> None:
        self._update_result = update_result
        self._by_token = {}
        self._by_user = {}
        self.update_calls: list[tuple[int, SessionAuthorization]] = []

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

    async def list_active_sessions(self) -> list[SessionData]:
        return []

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        self.update_calls.append((user_id, authorization))
        return self._update_result


class FakeRoleRepository:
    """get_user_ids_for_role の戻り値を制御する fake。"""

    _user_ids: list[int]

    def __init__(self, user_ids: list[int] | None = None) -> None:
        self._user_ids = user_ids or []
        self.get_calls: list[int] = []

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        self.get_calls.append(role_id)
        return list(self._user_ids)


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
    role_repo: FakeRoleRepository | None = None,
) -> SessionAuthorizationService:
    return SessionAuthorizationService(
        permission_service=perm_svc,
        session_store=session_store,
        role_repository=role_repo or FakeRoleRepository(),
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


class TestRefreshUserAuthorizationIdempotent:
    """同じ role state への repeated refresh は duplicate を作らず同等の結果を返す。"""

    async def test_repeated_refresh_returns_same_status(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        svc = _make_service(perm_svc, session_store)

        first = await svc.refresh_user_authorization(user_id=1)
        second = await svc.refresh_user_authorization(user_id=1)

        assert first.status == AuthorizationRefreshStatus.REFRESHED
        assert second.status == AuthorizationRefreshStatus.REFRESHED

    async def test_repeated_refresh_produces_equivalent_authorization(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        svc = _make_service(perm_svc, session_store)

        first = await svc.refresh_user_authorization(user_id=1)
        second = await svc.refresh_user_authorization(user_id=1)

        assert first.authorization == second.authorization

    async def test_repeated_refresh_calls_update_twice(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        svc = _make_service(perm_svc, session_store)

        _ = await svc.refresh_user_authorization(user_id=1)
        _ = await svc.refresh_user_authorization(user_id=1)

        assert len(session_store.update_calls) == 2


class TestRefreshUserAuthorizationSequentialRoleChanges:
    """sequential role changes では latest refresh が最終的な認可を決める。"""

    async def test_latest_refresh_sets_final_authorization(
        self,
        session_store: FakeSessionStore,
    ) -> None:
        first_snapshot = SessionAuthorization(
            privileges=Privileges.NORMAL,
            role_ids=(1,),
        )
        second_snapshot = SessionAuthorization(
            privileges=Privileges.ADMIN,
            role_ids=(5,),
        )

        perm_svc = FakePermissionService(snapshot=first_snapshot)
        svc = _make_service(perm_svc, session_store)

        _ = await svc.refresh_user_authorization(user_id=1)

        # Change the role state
        perm_svc.snapshot = second_snapshot
        result = await svc.refresh_user_authorization(user_id=1)

        assert result.authorization == second_snapshot
        # Last update_authorization call got the latest snapshot
        assert session_store.update_calls[-1][1] == second_snapshot


# ── refresh_role_authorization ─────────────────────────────────────────


class TestRefreshRoleAuthorizationMultipleUsers:
    """role に割り当てられた全ユーザーの refresh 結果を集約する。"""

    async def test_returns_role_authorization_refresh_result(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        role_repo = FakeRoleRepository(user_ids=[1, 2, 3])
        svc = _make_service(perm_svc, session_store, role_repo=role_repo)

        result = await svc.refresh_role_authorization(role_id=10)

        assert isinstance(result, RoleAuthorizationRefreshResult)
        assert result.role_id == 10

    async def test_refreshes_all_assigned_users(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        role_repo = FakeRoleRepository(user_ids=[10, 20, 30])
        svc = _make_service(perm_svc, session_store, role_repo=role_repo)

        result = await svc.refresh_role_authorization(role_id=5)

        assert len(result.user_results) == 3
        user_ids = {r.user_id for r in result.user_results}
        assert user_ids == {10, 20, 30}

    async def test_all_refreshed_when_all_active(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        role_repo = FakeRoleRepository(user_ids=[1, 2])
        svc = _make_service(perm_svc, session_store, role_repo=role_repo)

        result = await svc.refresh_role_authorization(role_id=1)

        statuses = {r.status for r in result.user_results}
        assert statuses == {AuthorizationRefreshStatus.REFRESHED}


class TestRefreshRoleAuthorizationNoAssignedUsers:
    """割り当てユーザーがいない role は空結果を返す。"""

    async def test_empty_user_results(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        role_repo = FakeRoleRepository(user_ids=[])
        svc = _make_service(perm_svc, session_store, role_repo=role_repo)

        result = await svc.refresh_role_authorization(role_id=99)

        assert len(result.user_results) == 0
        assert result.role_id == 99


class TestRefreshRoleAuthorizationMixedOutcomes:
    """active user と offline user が混在する場合、outcome を正しく区別する。"""

    async def test_mixed_refreshed_and_no_active_session(
        self,
        perm_svc: FakePermissionService,
    ) -> None:
        """user 1 は active、user 2 は offline (update_authorization が False)。"""
        role_repo = FakeRoleRepository(user_ids=[1, 2])

        # SessionStore returns True for user 1, False for user 2
        class SelectiveSessionStore(FakeSessionStore):
            @override
            async def update_authorization(
                self,
                user_id: int,
                authorization: SessionAuthorization,
            ) -> bool:
                self.update_calls.append((user_id, authorization))
                return user_id == 1

        store = SelectiveSessionStore()
        svc = _make_service(perm_svc, store, role_repo=role_repo)

        result = await svc.refresh_role_authorization(role_id=1)

        assert len(result.user_results) == 2

        user1_result = next(r for r in result.user_results if r.user_id == 1)
        user2_result = next(r for r in result.user_results if r.user_id == 2)

        assert user1_result.status == AuthorizationRefreshStatus.REFRESHED
        assert user1_result.authorization is not None
        assert user2_result.status == AuthorizationRefreshStatus.NO_ACTIVE_SESSION
        assert user2_result.authorization is None


class TestRefreshRoleAuthorizationDelegatesToRoleRepo:
    """refresh_role_authorization は RoleRepository.get_user_ids_for_role を呼ぶ。"""

    async def test_calls_get_user_ids_for_role(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        role_repo = FakeRoleRepository(user_ids=[1])
        svc = _make_service(perm_svc, session_store, role_repo=role_repo)

        _ = await svc.refresh_role_authorization(role_id=42)

        assert role_repo.get_calls == [42]
