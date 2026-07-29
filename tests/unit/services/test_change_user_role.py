"""ユーザーrole変更command use-caseの契約を検証するtest module."""

from __future__ import annotations

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import AuthorizationRefreshStatus, SessionData
from osu_server.domain.identity.system_users import create_bancho_bot_identity
from osu_server.repositories.memory.queries.roles import InMemoryRoleQueryRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.identity import (
    ChangeUserRoleCommandInput,
    ChangeUserRoleCommandUseCase,
    ChangeUserRoleStatus,
)
from osu_server.services.commands.identity.session_authorization_service import (
    SessionAuthorizationService,
)
from osu_server.services.queries.identity.permission_service import PermissionService
from tests.factories.domain import make_user

_DEFAULT_ROLE = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
    position=0,
)
_MODERATOR_ROLE = Role(
    id=2,
    name="Moderator",
    permissions=Privileges.MODERATOR,
    position=10,
)
_SUPPORTER_ROLE = Role(
    id=4,
    name="Supporter",
    permissions=Privileges.NORMAL | Privileges.UNRESTRICTED | Privileges.SUPPORTER,
    position=15,
)
_ADMIN_ROLE = Role(
    id=3,
    name="Admin",
    permissions=Privileges.ADMIN,
    position=20,
)


def _make_use_case() -> tuple[
    ChangeUserRoleCommandUseCase,
    InMemoryUnitOfWorkFactory,
    InMemorySessionStore,
]:
    """role変更test用のuse caseとmemory依存を作成する.

    Returns:
        tuple[ChangeUserRoleCommandUseCase, InMemoryUnitOfWorkFactory, InMemorySessionStore]:
            use caseとrole stateおよびsession stateを確認する依存object.
    """
    uow_factory = InMemoryUnitOfWorkFactory()
    uow_factory.seed_roles([_DEFAULT_ROLE, _MODERATOR_ROLE, _SUPPORTER_ROLE, _ADMIN_ROLE])
    role_query_repository = InMemoryRoleQueryRepository(uow_factory)
    session_store = InMemorySessionStore()
    session_authorization_service = SessionAuthorizationService(
        permission_service=PermissionService(role_query_repository),
        session_store=session_store,
        role_repository=role_query_repository,
    )
    return (
        ChangeUserRoleCommandUseCase(
            uow_factory=uow_factory,
            session_authorization_service=session_authorization_service,
        ),
        uow_factory,
        session_store,
    )


class _LeaderboardWakeRecorder:
    """leaderboard再構築依頼を記録するwake gateway fake.

    Attributes:
        user_calls (list[tuple[int, str]]): user再構築依頼のuser IDとreasonの履歴.
    """

    def __init__(self) -> None:
        """空のuser再構築依頼履歴を持つfakeを初期化する."""
        self.user_calls: list[tuple[int, str]] = []

    async def wake_user_rebuild(self, *, user_id: int, reason: str) -> None:
        """user単位のleaderboard再構築依頼を記録する.

        Args:
            user_id (int): 再構築対象userのID.
            reason (str): 再構築を要求した理由.

        Returns:
            None: 再構築依頼を記録し呼出し側へ値を返さない.
        """
        self.user_calls.append((user_id, reason))

    async def wake_beatmapset_rebuild(self, *, beatmapset_id: int, reason: str) -> None:
        """beatmapset再構築依頼を受理して副作用なく完了する.

        Args:
            beatmapset_id (int): 再構築対象beatmapsetのID.
            reason (str): 再構築を要求した理由.

        Returns:
            None: test対象外のbeatmapset依頼を無視して完了する.
        """
        _ = (beatmapset_id, reason)


class _FailingLeaderboardWake:
    """user再構築依頼を失敗させるwake gateway fake."""

    async def wake_user_rebuild(self, *, user_id: int, reason: str) -> None:
        """user再構築依頼時にqueue障害を送出する.

        Args:
            user_id (int): 再構築対象userのID.
            reason (str): 再構築を要求した理由.

        Returns:
            None: 成功値を返さず例外を送出する.

        Raises:
            RuntimeError: 再構築依頼をqueueへ投入できない場合.
        """
        _ = (user_id, reason)
        msg = "rebuild enqueue failed"
        raise RuntimeError(msg)

    async def wake_beatmapset_rebuild(self, *, beatmapset_id: int, reason: str) -> None:
        """beatmapset再構築依頼を受理して副作用なく完了する.

        Args:
            beatmapset_id (int): 再構築対象beatmapsetのID.
            reason (str): 再構築を要求した理由.

        Returns:
            None: test対象外のbeatmapset依頼を無視して完了する.
        """
        _ = (beatmapset_id, reason)


def _make_session(
    *,
    user_id: int,
    privileges: Privileges,
    role_ids: tuple[int, ...],
) -> SessionData:
    """指定されたauthorizationを持つtest用session dataを作成する.

    Args:
        user_id (int): sessionを所有するuserのID.
        privileges (Privileges): sessionへ反映するprivilege集合.
        role_ids (tuple[int, ...]): sessionへ反映するrole ID群.

    Returns:
        SessionData: role変更前後のsession authorizationを比較するtest data.
    """
    return SessionData(
        user_id=user_id,
        username="TargetUser",
        privileges=int(privileges),
        country="JP",
        osu_version="b20240601",
        utc_offset=9,
        display_city=False,
        client_hashes="hashes",
        pm_private=False,
        role_ids=role_ids,
    )


async def _seed_user(
    uow_factory: InMemoryUnitOfWorkFactory,
    *,
    username: str = "TargetUser",
    role_ids: tuple[int, ...] = (),
) -> int:
    """role変更対象となる通常userをmemory repositoryへ登録する.

    Args:
        uow_factory (InMemoryUnitOfWorkFactory): userとroleを登録するmemory Unit of Work factory.
        username (str): 登録するuserの表示名.
        role_ids (tuple[int, ...]): 初期状態で割り当てるrole ID群.

    Returns:
        int: 登録済みuserの永続化ID.
    """
    async with uow_factory() as uow:
        user = await uow.users.create(
            make_user(
                id=0,
                username=username,
                email=f"{username.lower()}@example.com",
            )
        )
        for role_id in role_ids:
            await uow.roles.assign_role(user.id, role_id)
        await uow.commit()
        return user.id


async def test_change_user_role_replaces_existing_roles_with_target_role() -> None:
    """既存role集合をtarget roleだけへ置換する契約を検証する.

    複数roleを持つ通常userをAdminへ変更し永続化結果とauthorization refresh状態を確認する.

    Returns:
        None: role置換結果とobservableな変更metadataを検証して完了する.
    """
    use_case, uow_factory, _ = _make_use_case()
    user_id = await _seed_user(
        uow_factory,
        role_ids=(_DEFAULT_ROLE.id, _MODERATOR_ROLE.id),
    )

    result = await use_case.execute(
        ChangeUserRoleCommandInput(
            username="TargetUser",
            role_name="Admin",
        )
    )

    assert result.status is ChangeUserRoleStatus.CHANGED
    assert result.changed is True
    assert result.user_id == user_id
    assert result.role_id == _ADMIN_ROLE.id
    assert result.previous_role_names == ("Default", "Moderator")
    assert result.authorization_refresh_status is AuthorizationRefreshStatus.NO_ACTIVE_SESSION
    roles = await InMemoryRoleQueryRepository(uow_factory).get_roles_for_user(user_id)
    assert [role.name for role in roles] == ["Admin"]


async def test_change_user_role_wakes_leaderboard_rebuild_after_role_change() -> None:
    """visibilityを変えるrole変更後にleaderboard再構築を要求する契約を検証する.

    Default roleのuserをAdminへ変更しuser単位のwake reasonが記録されることを確認する.

    Returns:
        None: 変更結果とleaderboard wake依頼を検証して完了する.
    """
    _, uow_factory, _ = _make_use_case()
    wake = _LeaderboardWakeRecorder()
    role_query_repository = InMemoryRoleQueryRepository(uow_factory)
    session_store = InMemorySessionStore()
    session_authorization_service = SessionAuthorizationService(
        permission_service=PermissionService(role_query_repository),
        session_store=session_store,
        role_repository=role_query_repository,
    )
    use_case = ChangeUserRoleCommandUseCase(
        uow_factory=uow_factory,
        session_authorization_service=session_authorization_service,
        leaderboard_rebuild_wake=wake,
    )
    user_id = await _seed_user(uow_factory, role_ids=(_DEFAULT_ROLE.id,))

    result = await use_case.execute(
        ChangeUserRoleCommandInput(
            username="TargetUser",
            role_name="Admin",
        )
    )

    assert result.status is ChangeUserRoleStatus.CHANGED
    assert result.leaderboard_rebuild_requested is True
    assert result.leaderboard_rebuild_failed is False
    assert wake.user_calls == [(user_id, "user_visibility_changed")]


async def test_change_user_role_does_not_wake_leaderboard_rebuild_when_unchanged() -> None:
    """同一role指定ではleaderboard再構築を要求しない契約を検証する.

    既にAdmin roleだけを持つuserへ同じroleを指定しUNCHANGEDとwakeなしを確認する.

    Returns:
        None: no-op結果とwake履歴が空であることを検証して完了する.
    """
    _, uow_factory, _ = _make_use_case()
    wake = _LeaderboardWakeRecorder()
    role_query_repository = InMemoryRoleQueryRepository(uow_factory)
    session_authorization_service = SessionAuthorizationService(
        permission_service=PermissionService(role_query_repository),
        session_store=InMemorySessionStore(),
        role_repository=role_query_repository,
    )
    use_case = ChangeUserRoleCommandUseCase(
        uow_factory=uow_factory,
        session_authorization_service=session_authorization_service,
        leaderboard_rebuild_wake=wake,
    )
    _ = await _seed_user(uow_factory, role_ids=(_ADMIN_ROLE.id,))

    result = await use_case.execute(
        ChangeUserRoleCommandInput(
            username="TargetUser",
            role_name="Admin",
        )
    )

    assert result.status is ChangeUserRoleStatus.UNCHANGED
    assert result.leaderboard_rebuild_requested is False
    assert wake.user_calls == []


async def test_change_user_role_does_not_wake_when_visibility_is_unchanged() -> None:
    """visibilityを変えないrole変更ではleaderboard再構築を要求しない契約を検証する.

    Default roleのuserをSupporterへ変更し変更成功とwakeなしを確認する.

    Returns:
        None: role変更結果とwake履歴が空であることを検証して完了する.
    """
    _, uow_factory, _ = _make_use_case()
    wake = _LeaderboardWakeRecorder()
    role_query_repository = InMemoryRoleQueryRepository(uow_factory)
    session_authorization_service = SessionAuthorizationService(
        permission_service=PermissionService(role_query_repository),
        session_store=InMemorySessionStore(),
        role_repository=role_query_repository,
    )
    use_case = ChangeUserRoleCommandUseCase(
        uow_factory=uow_factory,
        session_authorization_service=session_authorization_service,
        leaderboard_rebuild_wake=wake,
    )
    _ = await _seed_user(uow_factory, role_ids=(_DEFAULT_ROLE.id,))

    result = await use_case.execute(
        ChangeUserRoleCommandInput(
            username="TargetUser",
            role_name="Supporter",
        )
    )

    assert result.status is ChangeUserRoleStatus.CHANGED
    assert result.leaderboard_rebuild_requested is False
    assert wake.user_calls == []


async def test_change_user_role_wake_failure_does_not_rollback_role_change() -> None:
    """Leaderboard wake障害がrole変更をrollbackしない契約を検証する.

    wake gatewayが例外を送出する状態でAdminへ変更しrole永続化とfailure metadataを確認する.

    Returns:
        None: role変更の成功状態とwake障害の記録を検証して完了する.
    """
    _, uow_factory, _ = _make_use_case()
    role_query_repository = InMemoryRoleQueryRepository(uow_factory)
    session_authorization_service = SessionAuthorizationService(
        permission_service=PermissionService(role_query_repository),
        session_store=InMemorySessionStore(),
        role_repository=role_query_repository,
    )
    use_case = ChangeUserRoleCommandUseCase(
        uow_factory=uow_factory,
        session_authorization_service=session_authorization_service,
        leaderboard_rebuild_wake=_FailingLeaderboardWake(),
    )
    user_id = await _seed_user(uow_factory, role_ids=(_DEFAULT_ROLE.id,))

    result = await use_case.execute(
        ChangeUserRoleCommandInput(
            username="TargetUser",
            role_name="Admin",
        )
    )

    assert result.status is ChangeUserRoleStatus.CHANGED
    assert result.leaderboard_rebuild_requested is True
    assert result.leaderboard_rebuild_failed is True
    assert result.leaderboard_rebuild_error == "rebuild enqueue failed"
    roles = await InMemoryRoleQueryRepository(uow_factory).get_roles_for_user(user_id)
    assert [role.name for role in roles] == ["Admin"]


async def test_change_user_role_refreshes_session_for_existing_single_role() -> None:
    """同一roleでもactive session authorizationをrefreshする契約を検証する.

    Admin roleを持つuserのstale sessionを用意しUNCHANGED後のprivilegeとrole IDを確認する.

    Returns:
        None: refresh状態と更新済みsession authorizationを検証して完了する.
    """
    use_case, uow_factory, session_store = _make_use_case()
    user_id = await _seed_user(uow_factory, role_ids=(_ADMIN_ROLE.id,))
    await session_store.create(
        user_id=user_id,
        token="token-admin",
        data=_make_session(
            user_id=user_id,
            privileges=_DEFAULT_ROLE.permissions,
            role_ids=(_DEFAULT_ROLE.id,),
        ),
    )

    result = await use_case.execute(
        ChangeUserRoleCommandInput(
            username="TargetUser",
            role_name="Admin",
        )
    )

    assert result.status is ChangeUserRoleStatus.UNCHANGED
    assert result.changed is False
    assert result.user_id == user_id
    assert result.previous_role_names == ("Admin",)
    assert result.authorization_refresh_status is AuthorizationRefreshStatus.REFRESHED
    roles = await InMemoryRoleQueryRepository(uow_factory).get_roles_for_user(user_id)
    assert [role.name for role in roles] == ["Admin"]
    session = await session_store.get_by_user(user_id)
    assert session is not None
    assert session.privileges == int(_ADMIN_ROLE.permissions)
    assert session.role_ids == (_ADMIN_ROLE.id,)


async def test_change_user_role_refreshes_active_session_after_role_change() -> None:
    """role変更後にactive session authorizationをrefreshする契約を検証する.

    Default roleからAdminへの変更後にsessionのprivilegeとrole IDが更新されることを確認する.

    Returns:
        None: role変更結果と更新済みsession authorizationを検証して完了する.
    """
    use_case, uow_factory, session_store = _make_use_case()
    user_id = await _seed_user(uow_factory, role_ids=(_DEFAULT_ROLE.id,))
    await session_store.create(
        user_id=user_id,
        token="token-target",
        data=_make_session(
            user_id=user_id,
            privileges=_DEFAULT_ROLE.permissions,
            role_ids=(_DEFAULT_ROLE.id,),
        ),
    )

    result = await use_case.execute(
        ChangeUserRoleCommandInput(
            username="TargetUser",
            role_name="Admin",
        )
    )

    assert result.status is ChangeUserRoleStatus.CHANGED
    assert result.authorization_refresh_status is AuthorizationRefreshStatus.REFRESHED
    session = await session_store.get_by_user(user_id)
    assert session is not None
    assert session.privileges == int(_ADMIN_ROLE.permissions)
    assert session.role_ids == (_ADMIN_ROLE.id,)


async def test_change_user_role_returns_user_not_found() -> None:
    """存在しないuserへのrole変更をnot-foundとして返す契約を検証する.

    未登録usernameと既存role名を指定してUSER_NOT_FOUNDが返ることを確認する.

    Returns:
        None: not-found結果を検証して完了する.
    """
    use_case, _, _ = _make_use_case()

    result = await use_case.execute(
        ChangeUserRoleCommandInput(
            username="MissingUser",
            role_name="Admin",
        )
    )

    assert result.status is ChangeUserRoleStatus.USER_NOT_FOUND


async def test_change_user_role_returns_role_not_found_without_changing_roles() -> None:
    """存在しないrole指定が既存role集合を変えない契約を検証する.

    Default roleを持つuserへ未登録role名を指定してROLE_NOT_FOUNDと元の割当を確認する.

    Returns:
        None: not-found結果と不変のrole集合を検証して完了する.
    """
    use_case, uow_factory, _ = _make_use_case()
    user_id = await _seed_user(uow_factory, role_ids=(_DEFAULT_ROLE.id,))

    result = await use_case.execute(
        ChangeUserRoleCommandInput(
            username="TargetUser",
            role_name="MissingRole",
        )
    )

    assert result.status is ChangeUserRoleStatus.ROLE_NOT_FOUND
    roles = await InMemoryRoleQueryRepository(uow_factory).get_roles_for_user(user_id)
    assert [role.name for role in roles] == ["Default"]


async def test_change_user_role_rejects_system_user() -> None:
    """System userへのrole変更を拒否して既存割当を保つ契約を検証する.

    BanchoBot identityへAdmin roleを指定してSYSTEM_USER_DENIEDとDefault role維持を確認する.

    Returns:
        None: system userの拒否結果と不変のrole集合を検証して完了する.
    """
    use_case, uow_factory, _ = _make_use_case()
    async with uow_factory() as uow:
        await uow.users.sync_system_user(create_bancho_bot_identity("BanchoBot"))
        await uow.roles.assign_role(1, _DEFAULT_ROLE.id)
        await uow.commit()

    result = await use_case.execute(
        ChangeUserRoleCommandInput(
            username="BanchoBot",
            role_name="Admin",
        )
    )

    assert result.status is ChangeUserRoleStatus.SYSTEM_USER_DENIED
    roles = await InMemoryRoleQueryRepository(uow_factory).get_roles_for_user(1)
    assert [role.name for role in roles] == ["Default"]
