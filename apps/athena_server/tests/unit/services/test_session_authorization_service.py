"""SessionAuthorizationServiceのuser/role認可更新契約を検証するmodule.

permission計算,active session更新,role所属user検索を制御するfakeを用いて,
refresh結果と副作用を対象にする.
"""

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
    """SessionAuthorization計算の成功値または失敗を制御するfake.

    Attributes:
        snapshot (SessionAuthorization): 成功時に返す認可snapshot.
        _should_fail (bool): 計算時にRuntimeErrorを送出するか.
        compute_calls (list[int]): 認可計算を要求されたuser IDの履歴.
    """

    snapshot: SessionAuthorization
    _should_fail: bool

    def __init__(
        self,
        snapshot: SessionAuthorization | None = None,
        *,
        should_fail: bool = False,
    ) -> None:
        """固定snapshotまたは失敗動作を持つfakeを初期化する.

        Args:
            snapshot (SessionAuthorization | None): 成功時に返す認可snapshot.
                Noneなら標準snapshotを使う.
            should_fail (bool): Trueなら認可計算時にRuntimeErrorを送出する.
        """
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
        """要求user IDを記録して設定済み認可snapshotを返す.

        Args:
            user_id (int): 認可計算を要求するuserの識別子.

        Returns:
            SessionAuthorization: 設定済みの認可snapshot.

        Raises:
            RuntimeError: should_failがTrueの場合.
        """
        self.compute_calls.append(user_id)
        if self._should_fail:
            raise RuntimeError("compute failed")
        return self.snapshot


class FakeSessionStore:
    """認可更新の成否と呼出し履歴を制御するsession store fake.

    Attributes:
        _update_result (bool): update_authorizationが返す成功状態.
        _by_token (dict[str, SessionData]): protocol互換のtoken lookup用空state.
        _by_user (dict[int, SessionData]): protocol互換のuser lookup用空state.
        update_calls (list[tuple[int, SessionAuthorization]]): 認可更新要求の履歴.
    """

    _update_result: bool
    _by_token: dict[str, SessionData]
    _by_user: dict[int, SessionData]

    def __init__(self, *, update_result: bool = True) -> None:
        """認可更新の固定成功状態を持つfakeを初期化する.

        Args:
            update_result (bool): active sessionが存在するように返す更新結果.
        """
        self._update_result = update_result
        self._by_token = {}
        self._by_user = {}
        self.update_calls: list[tuple[int, SessionAuthorization]] = []

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        """Create protocolを副作用なしで受け入れる.

        Args:
            user_id (int): sessionを紐付けるuserの識別子.
            token (str): sessionのtoken.
            data (SessionData): 保存対象のsession data.

        Returns:
            None: fake stateを変更せず,呼び出し側へ値を返さずに完了する.
        """
        _ = (user_id, token, data)

    async def get(self, token: str) -> SessionData | None:
        """Token単位session lookupを未実装のNoneとして返す.

        Args:
            token (str): sessionを取得するtoken.

        Returns:
            SessionData | None: token lookupを保持しないためNone.
        """
        _ = token
        return None

    async def get_by_user(self, user_id: int) -> SessionData | None:
        """User単位session lookupを未実装のNoneとして返す.

        Args:
            user_id (int): sessionを取得するuserの識別子.

        Returns:
            SessionData | None: user lookupを保持しないためNone.
        """
        _ = user_id
        return None

    async def delete(self, token: str) -> None:
        """Token deletion protocolを副作用なしで受け入れる.

        Args:
            token (str): 削除対象のsession token.

        Returns:
            None: fake stateを変更せず,呼び出し側へ値を返さずに完了する.
        """
        _ = token

    async def exists(self, token: str) -> bool:
        """Tokenが存在しない固定結果を返す.

        Args:
            token (str): 存在確認するsession token.

        Returns:
            bool: token単位stateを保持しないためFalse.
        """
        _ = token
        return False

    async def refresh(self, token: str) -> bool:
        """Token refreshを行わない固定結果を返す.

        Args:
            token (str): refresh対象のsession token.

        Returns:
            bool: token単位stateを保持しないためFalse.
        """
        _ = token
        return False

    async def delete_by_user(self, user_id: int) -> None:
        """User単位deletion protocolを副作用なしで受け入れる.

        Args:
            user_id (int): session削除対象のuserの識別子.

        Returns:
            None: fake stateを変更せず,呼び出し側へ値を返さずに完了する.
        """
        _ = user_id

    async def list_active_sessions(self) -> list[SessionData]:
        """Active sessionがない固定の空listを返す.

        Returns:
            list[SessionData]: fakeが保持しないactive sessionの空list.
        """
        return []

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        """認可更新要求を記録して設定済みの更新結果を返す.

        Args:
            user_id (int): 認可を更新するuserの識別子.
            authorization (SessionAuthorization): active sessionへ適用する認可snapshot.

        Returns:
            bool: 設定済みのactive session存在状態.
        """
        self.update_calls.append((user_id, authorization))
        return self._update_result


class FakeRoleRepository:
    """Role所属user IDの戻り値とlookup履歴を制御するfake.

    Attributes:
        _user_ids (list[int]): 指定roleに所属するとして返すuser ID群.
        get_calls (list[int]): user ID検索を要求されたrole IDの履歴.
    """

    _user_ids: list[int]

    def __init__(self, user_ids: list[int] | None = None) -> None:
        """固定のrole所属user ID群を持つfakeを初期化する.

        Args:
            user_ids (list[int] | None): 検索時に返すuser ID群. Noneなら空listを使う.
        """
        self._user_ids = user_ids or []
        self.get_calls: list[int] = []

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        """Role IDを記録して固定の所属user ID群を返す.

        Args:
            role_id (int): 所属userを検索するroleの識別子.

        Returns:
            list[int]: 初期化時に設定したuser ID群のcopy.
        """
        self.get_calls.append(role_id)
        return list(self._user_ids)


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def perm_svc() -> FakePermissionService:
    """成功するSessionAuthorization計算fakeをfixtureとして提供する.

    Returns:
        FakePermissionService: 標準の認可snapshotを返す新規fake.
    """
    return FakePermissionService()


@pytest.fixture
def session_store() -> FakeSessionStore:
    """認可更新成功を返すsession store fakeをfixtureとして提供する.

    Returns:
        FakeSessionStore: update_authorizationがTrueとなる新規fake.
    """
    return FakeSessionStore()


def _make_service(
    perm_svc: FakePermissionService,
    session_store: FakeSessionStore,
    role_repo: FakeRoleRepository | None = None,
) -> SessionAuthorizationService:
    """指定fakeを接続したSessionAuthorizationServiceを作成する.

    Args:
        perm_svc (FakePermissionService): 認可snapshotを計算するfake service.
        session_store (FakeSessionStore): active session認可を更新するfake store.
        role_repo (FakeRoleRepository | None): role所属userを検索するfake. Noneなら空のfakeを使う.

    Returns:
        SessionAuthorizationService: test対象の依存解決済みservice.
    """
    return SessionAuthorizationService(
        permission_service=perm_svc,
        session_store=session_store,
        role_repository=role_repo or FakeRoleRepository(),
    )


# ── refresh_user_authorization ─────────────────────────────────────────


class TestRefreshUserAuthorizationRefreshed:
    """Active sessionを更新できた場合のuser認可refresh契約を検証する."""

    async def test_returns_refreshed_status(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        """認可更新成功時にREFRESHED statusを返す契約を検証する.

        Args:
            perm_svc (FakePermissionService): 成功する認可計算fake.
            session_store (FakeSessionStore): 認可更新成功を返すsession store fake.

        Returns:
            None: refresh statusを検証して完了し,呼び出し側へ値を返さない.
        """
        svc = _make_service(perm_svc, session_store)

        result = await svc.refresh_user_authorization(user_id=1)

        assert result.status == AuthorizationRefreshStatus.REFRESHED

    async def test_returns_new_authorization_snapshot(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        """認可更新成功時に計算済みsnapshotを結果へ含める契約を検証する.

        Args:
            perm_svc (FakePermissionService): 置換可能な認可snapshotを返すfake.
            session_store (FakeSessionStore): 認可更新成功を返すsession store fake.

        Returns:
            None: 計算済みsnapshotとrefresh結果の一致を検証して完了し,呼び出し側へ値を返さない.
        """
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
        """Refresh結果が要求されたuser IDを保持する契約を検証する.

        Args:
            perm_svc (FakePermissionService): 成功する認可計算fake.
            session_store (FakeSessionStore): 認可更新成功を返すsession store fake.

        Returns:
            None: 入力user IDとrefresh結果の一致を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = _make_service(perm_svc, session_store)

        result = await svc.refresh_user_authorization(user_id=42)

        assert result.user_id == 42

    async def test_calls_compute_session_authorization(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        """Refreshが対象userの認可計算を一度要求する契約を検証する.

        Args:
            perm_svc (FakePermissionService): 認可計算要求を記録するfake.
            session_store (FakeSessionStore): 認可更新成功を返すsession store fake.

        Returns:
            None: 認可計算fakeへの入力履歴を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = _make_service(perm_svc, session_store)

        _ = await svc.refresh_user_authorization(user_id=7)

        assert perm_svc.compute_calls == [7]

    async def test_calls_update_authorization_with_snapshot(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        """Refreshが計算済みsnapshotをactive sessionへ適用する契約を検証する.

        Args:
            perm_svc (FakePermissionService): 適用する認可snapshotを返すfake.
            session_store (FakeSessionStore): 認可更新要求を記録するsession store fake.

        Returns:
            None: 更新要求のuser IDとsnapshotを検証して完了し,呼び出し側へ値を返さない.
        """
        svc = _make_service(perm_svc, session_store)

        _ = await svc.refresh_user_authorization(user_id=3)

        assert len(session_store.update_calls) == 1
        call_user_id, call_auth = session_store.update_calls[0]
        assert call_user_id == 3
        assert call_auth == perm_svc.snapshot


class TestRefreshUserAuthorizationNoActiveSession:
    """Active sessionがない場合のuser認可refresh契約を検証する."""

    async def test_returns_no_active_session(
        self,
        perm_svc: FakePermissionService,
    ) -> None:
        """認可更新先がない場合にNO_ACTIVE_SESSIONを返す契約を検証する.

        Args:
            perm_svc (FakePermissionService): 成功する認可計算fake.

        Returns:
            None: active session不在のrefresh statusを検証して完了し,呼び出し側へ値を返さない.
        """
        store = FakeSessionStore(update_result=False)
        svc = _make_service(perm_svc, store)

        result = await svc.refresh_user_authorization(user_id=1)

        assert result.status == AuthorizationRefreshStatus.NO_ACTIVE_SESSION

    async def test_authorization_is_none(
        self,
        perm_svc: FakePermissionService,
    ) -> None:
        """Active session不在の結果にauthorizationを含めない契約を検証する.

        Args:
            perm_svc (FakePermissionService): 成功する認可計算fake.

        Returns:
            None: authorizationがNoneのrefresh結果を検証して完了し,呼び出し側へ値を返さない.
        """
        store = FakeSessionStore(update_result=False)
        svc = _make_service(perm_svc, store)

        result = await svc.refresh_user_authorization(user_id=1)

        assert result.authorization is None

    async def test_still_attempts_update(
        self,
        perm_svc: FakePermissionService,
    ) -> None:
        """Active session不在でも認可更新を一度試行する契約を検証する.

        Args:
            perm_svc (FakePermissionService): 成功する認可計算fake.

        Returns:
            None: 更新要求が記録されることを検証して完了し,呼び出し側へ値を返さない.
        """
        store = FakeSessionStore(update_result=False)
        svc = _make_service(perm_svc, store)

        _ = await svc.refresh_user_authorization(user_id=1)

        # update_authorization was called; compute succeeded but store said no session
        assert len(store.update_calls) == 1


class TestRefreshUserAuthorizationFailed:
    """認可snapshot計算が失敗した場合のuser refresh契約を検証する."""

    async def test_returns_failed(
        self,
        session_store: FakeSessionStore,
    ) -> None:
        """認可計算例外をFAILED statusへ変換する契約を検証する.

        Args:
            session_store (FakeSessionStore): 更新要求を記録するsession store fake.

        Returns:
            None: 計算失敗時のrefresh statusを検証して完了し,呼び出し側へ値を返さない.
        """
        perm_svc = FakePermissionService(should_fail=True)
        svc = _make_service(perm_svc, session_store)

        result = await svc.refresh_user_authorization(user_id=1)

        assert result.status == AuthorizationRefreshStatus.FAILED

    async def test_authorization_is_none_on_failure(
        self,
        session_store: FakeSessionStore,
    ) -> None:
        """認可計算失敗の結果にauthorizationを含めない契約を検証する.

        Args:
            session_store (FakeSessionStore): 更新要求を記録するsession store fake.

        Returns:
            None: authorizationがNoneの失敗結果を検証して完了し,呼び出し側へ値を返さない.
        """
        perm_svc = FakePermissionService(should_fail=True)
        svc = _make_service(perm_svc, session_store)

        result = await svc.refresh_user_authorization(user_id=1)

        assert result.authorization is None

    async def test_does_not_call_update_on_failure(
        self,
        session_store: FakeSessionStore,
    ) -> None:
        """認可計算失敗時にactive sessionを更新しない契約を検証する.

        Args:
            session_store (FakeSessionStore): 更新要求を記録するsession store fake.

        Returns:
            None: 更新要求が空であることを検証して完了し,呼び出し側へ値を返さない.
        """
        perm_svc = FakePermissionService(should_fail=True)
        svc = _make_service(perm_svc, session_store)

        _ = await svc.refresh_user_authorization(user_id=1)

        assert len(session_store.update_calls) == 0


class TestRefreshUserAuthorizationIdempotent:
    """同一role stateへの反復user認可refresh契約を検証する."""

    async def test_repeated_refresh_returns_same_status(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        """反復refreshが同じREFRESHED statusを返す契約を検証する.

        Args:
            perm_svc (FakePermissionService): 一貫した認可snapshotを返すfake.
            session_store (FakeSessionStore): 認可更新成功を返すsession store fake.

        Returns:
            None: 2回のrefresh statusを検証して完了し,呼び出し側へ値を返さない.
        """
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
        """反復refreshが同値のauthorizationを返す契約を検証する.

        Args:
            perm_svc (FakePermissionService): 一貫した認可snapshotを返すfake.
            session_store (FakeSessionStore): 認可更新成功を返すsession store fake.

        Returns:
            None: 2回のauthorization結果の同値性を検証して完了し,呼び出し側へ値を返さない.
        """
        svc = _make_service(perm_svc, session_store)

        first = await svc.refresh_user_authorization(user_id=1)
        second = await svc.refresh_user_authorization(user_id=1)

        assert first.authorization == second.authorization

    async def test_repeated_refresh_calls_update_twice(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        """反復refreshが各回でactive session更新を試行する契約を検証する.

        Args:
            perm_svc (FakePermissionService): 一貫した認可snapshotを返すfake.
            session_store (FakeSessionStore): 更新要求を記録するsession store fake.

        Returns:
            None: 2回の更新要求が記録されることを検証して完了し,呼び出し側へ値を返さない.
        """
        svc = _make_service(perm_svc, session_store)

        _ = await svc.refresh_user_authorization(user_id=1)
        _ = await svc.refresh_user_authorization(user_id=1)

        assert len(session_store.update_calls) == 2


class TestRefreshUserAuthorizationSequentialRoleChanges:
    """連続role変更後のuser認可refresh契約を検証する."""

    async def test_latest_refresh_sets_final_authorization(
        self,
        session_store: FakeSessionStore,
    ) -> None:
        """最新の認可snapshotが最後のrefresh結果と更新要求に残る契約を検証する.

        Args:
            session_store (FakeSessionStore): 更新要求を記録するsession store fake.

        Returns:
            None: 最新snapshotによる結果と最終更新要求を検証して完了し,呼び出し側へ値を返さない.
        """
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
    """Role所属user全員の認可refresh集約契約を検証する."""

    async def test_returns_role_authorization_refresh_result(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        """Role refreshがrole IDを持つ集約結果型を返す契約を検証する.

        Args:
            perm_svc (FakePermissionService): 成功する認可計算fake.
            session_store (FakeSessionStore): 認可更新成功を返すsession store fake.

        Returns:
            None: 集約結果の型とrole IDを検証して完了し,呼び出し側へ値を返さない.
        """
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
        """Role所属の全userをrefresh対象にする契約を検証する.

        Args:
            perm_svc (FakePermissionService): 成功する認可計算fake.
            session_store (FakeSessionStore): 認可更新成功を返すsession store fake.

        Returns:
            None: 所属user全員のrefresh結果を検証して完了し,呼び出し側へ値を返さない.
        """
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
        """全所属userにactive sessionがあれば全結果をREFRESHEDにする契約を検証する.

        Args:
            perm_svc (FakePermissionService): 成功する認可計算fake.
            session_store (FakeSessionStore): 認可更新成功を返すsession store fake.

        Returns:
            None: 全userのrefresh status集合を検証して完了し,呼び出し側へ値を返さない.
        """
        role_repo = FakeRoleRepository(user_ids=[1, 2])
        svc = _make_service(perm_svc, session_store, role_repo=role_repo)

        result = await svc.refresh_role_authorization(role_id=1)

        statuses = {r.status for r in result.user_results}
        assert statuses == {AuthorizationRefreshStatus.REFRESHED}


class TestRefreshRoleAuthorizationNoAssignedUsers:
    """Role所属userがいない場合の認可refresh契約を検証する."""

    async def test_empty_user_results(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        """所属userがないroleに空のuser結果を返す契約を検証する.

        Args:
            perm_svc (FakePermissionService): 認可計算fake.
            session_store (FakeSessionStore): session store fake.

        Returns:
            None: 空のuser結果と入力role IDを検証して完了し,呼び出し側へ値を返さない.
        """
        role_repo = FakeRoleRepository(user_ids=[])
        svc = _make_service(perm_svc, session_store, role_repo=role_repo)

        result = await svc.refresh_role_authorization(role_id=99)

        assert len(result.user_results) == 0
        assert result.role_id == 99


class TestRefreshRoleAuthorizationMixedOutcomes:
    """Active userとoffline userが混在するrole認可refresh契約を検証する."""

    async def test_mixed_refreshed_and_no_active_session(
        self,
        perm_svc: FakePermissionService,
    ) -> None:
        """Userごとのsession存在状態を別々のrefresh結果へ反映する契約を検証する.

        Args:
            perm_svc (FakePermissionService): 成功する認可計算fake.

        Returns:
            None: active userのREFRESHEDとoffline userのNO_ACTIVE_SESSIONを検証して完了する.
                呼び出し側へ値を返さない.
        """
        role_repo = FakeRoleRepository(user_ids=[1, 2])

        # SessionStore returns True for user 1, False for user 2
        class SelectiveSessionStore(FakeSessionStore):
            """User IDごとに認可更新の成功状態を切り替えるsession store fake."""

            @override
            async def update_authorization(
                self,
                user_id: int,
                authorization: SessionAuthorization,
            ) -> bool:
                """User ID 1だけをactive sessionありとして認可更新する.

                Args:
                    user_id (int): 認可を更新するuserの識別子.
                    authorization (SessionAuthorization): 更新要求として記録する認可snapshot.

                Returns:
                    bool: user ID 1の場合はTrue. それ以外はFalse.
                """
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
    """Role認可refreshのrepository delegation契約を検証する."""

    async def test_calls_get_user_ids_for_role(
        self,
        perm_svc: FakePermissionService,
        session_store: FakeSessionStore,
    ) -> None:
        """Role refreshが指定role IDで所属userを検索する契約を検証する.

        Args:
            perm_svc (FakePermissionService): 成功する認可計算fake.
            session_store (FakeSessionStore): 認可更新成功を返すsession store fake.

        Returns:
            None: role repositoryへの検索入力を検証して完了し,呼び出し側へ値を返さない.
        """
        role_repo = FakeRoleRepository(user_ids=[1])
        svc = _make_service(perm_svc, session_store, role_repo=role_repo)

        _ = await svc.refresh_role_authorization(role_id=42)

        assert role_repo.get_calls == [42]
