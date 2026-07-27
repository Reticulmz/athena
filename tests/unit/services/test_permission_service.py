"""PermissionServiceのrole由来authorization計算契約を検証するmodule.

in-memory role repositoryを用いてPrivileges,SessionAuthorization,関連logの
observable outcomeを対象にする.
"""

from __future__ import annotations

from structlog.testing import capture_logs

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import SessionAuthorization
from osu_server.repositories.memory.queries.roles import InMemoryRoleQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.queries.identity.permission_service import PermissionService

# ── Seed data ────────────────────────────────────────────────────────

ROLE_DEFAULT = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
    position=0,
)
ROLE_SUPPORTER = Role(id=2, name="Supporter", permissions=Privileges.SUPPORTER, position=1)
ROLE_MODERATOR = Role(id=3, name="Moderator", permissions=Privileges.MODERATOR, position=2)
ROLE_ADMIN = Role(id=4, name="Admin", permissions=Privileges.ADMIN, position=3)
ROLE_DEVELOPER = Role(id=5, name="Developer", permissions=Privileges.DEVELOPER, position=4)

ALL_ROLES = [ROLE_DEFAULT, ROLE_SUPPORTER, ROLE_MODERATOR, ROLE_ADMIN, ROLE_DEVELOPER]


class RoleAssignmentHarness:
    """in-memory role assignmentをcommitしてtest状態を準備するharness.

    Attributes:
        _uow_factory (InMemoryUnitOfWorkFactory): role assignmentを保存するUnit of Work factory.
    """

    _uow_factory: InMemoryUnitOfWorkFactory

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Role assignment用のUnit of Work factoryを設定する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): seed済みroleを持つfactory.
        """
        self._uow_factory = uow_factory

    async def assign_role(self, *, user_id: int, role_id: int) -> None:
        """指定userへroleを割り当ててtransactionをcommitする.

        Args:
            user_id (int): roleを割り当てるuserの識別子.
            role_id (int): 割り当てるroleの識別子.

        Returns:
            None: role assignmentをcommitして完了し,呼び出し側へ値を返さない.
        """
        async with self._uow_factory() as uow:
            await uow.roles.assign_role(user_id=user_id, role_id=role_id)
            await uow.commit()


def _make_service(
    roles: list[Role] | None = None,
) -> tuple[PermissionService, RoleAssignmentHarness]:
    """seed済みPermissionServiceとrole assignment harnessを作成する.

    Args:
        roles (list[Role] | None): seedするrole集合. Noneの場合は標準の全roleを使う.

    Returns:
        tuple[PermissionService, RoleAssignmentHarness]: 権限計算serviceとassignment helper.
    """
    uow_factory = InMemoryUnitOfWorkFactory()
    uow_factory.seed_roles(ALL_ROLES if roles is None else roles)
    repo = InMemoryRoleQueryRepository(uow_factory)
    return PermissionService(role_repo=repo), RoleAssignmentHarness(uow_factory)


# ── compute_permissions ──────────────────────────────────────────────


class TestComputePermissionsSingleRole:
    """単一roleのPrivileges集約契約を検証する."""

    async def test_single_default_role(self) -> None:
        """Default roleだけのPrivilegesがそのまま返る契約を検証する.

        Returns:
            None: default roleのPrivileges結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)

        result = await svc.compute_permissions(user_id=1)

        assert result == ROLE_DEFAULT.permissions

    async def test_single_supporter_role(self) -> None:
        """Supporter roleだけのPrivilegesが返る契約を検証する.

        Returns:
            None: supporter roleのPrivileges結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        await repo.assign_role(user_id=2, role_id=ROLE_SUPPORTER.id)

        result = await svc.compute_permissions(user_id=2)

        assert result == Privileges.SUPPORTER


class TestComputePermissionsMultipleRoles:
    """複数roleのPrivileges OR集約契約を検証する."""

    async def test_default_plus_supporter(self) -> None:
        """defaultとsupporterのPrivilegesをOR結合する契約を検証する.

        Returns:
            None: 2つのroleからの集約結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)
        await repo.assign_role(user_id=1, role_id=ROLE_SUPPORTER.id)

        result = await svc.compute_permissions(user_id=1)

        expected = ROLE_DEFAULT.permissions | Privileges.SUPPORTER
        assert result == expected

    async def test_all_roles_combined(self) -> None:
        """全seed roleのPrivilegesをOR結合する契約を検証する.

        Returns:
            None: 全roleからの集約結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        for role in ALL_ROLES:
            await repo.assign_role(user_id=1, role_id=role.id)

        result = await svc.compute_permissions(user_id=1)

        expected = Privileges.NONE
        for role in ALL_ROLES:
            expected |= role.permissions
        assert result == expected

    async def test_moderator_plus_admin(self) -> None:
        """moderatorとadminのPrivilegesをOR結合する契約を検証する.

        Returns:
            None: 2つの管理roleからの集約結果を検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        await repo.assign_role(user_id=3, role_id=ROLE_MODERATOR.id)
        await repo.assign_role(user_id=3, role_id=ROLE_ADMIN.id)

        result = await svc.compute_permissions(user_id=3)

        assert result == (Privileges.MODERATOR | Privileges.ADMIN)


class TestComputePermissionsNoRoles:
    """role未割当userのPrivileges既定値契約を検証する."""

    async def test_no_roles_returns_none(self) -> None:
        """roleのないuserにPrivileges.NONEを返す契約を検証する.

        Returns:
            None: 未割当userの既定Privilegesを検証して完了し,呼び出し側へ値を返さない.
        """
        svc, _repo = _make_service()

        result = await svc.compute_permissions(user_id=999)

        assert result == Privileges.NONE


# ── permissions_computed ログイベント ────────────────────────────────


class TestPermissionsComputedLog:
    """compute_permissions時のpermissions_computed log契約を検証する."""

    async def test_emits_log_with_user_id_and_privileges(self) -> None:
        """単一roleの計算logがuser IDとPrivilegesを含む契約を検証する.

        Returns:
            None: 計算結果とpermissions_computed logを検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)

        with capture_logs() as cap_logs:
            result = await svc.compute_permissions(user_id=1)

        assert result == ROLE_DEFAULT.permissions
        events = [e for e in cap_logs if e["event"] == "permissions_computed"]
        assert len(events) == 1
        assert events[0]["user_id"] == 1
        assert events[0]["privileges"] == ROLE_DEFAULT.permissions
        assert events[0]["log_level"] == "info"

    async def test_emits_log_with_combined_privileges(self) -> None:
        """複数roleのOR集約結果がlogに記録される契約を検証する.

        Returns:
            None: 集約Privilegesとpermissions_computed logを検証して完了する.
                呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        await repo.assign_role(user_id=2, role_id=ROLE_DEFAULT.id)
        await repo.assign_role(user_id=2, role_id=ROLE_MODERATOR.id)

        with capture_logs() as cap_logs:
            result = await svc.compute_permissions(user_id=2)

        expected = ROLE_DEFAULT.permissions | Privileges.MODERATOR
        assert result == expected
        events = [e for e in cap_logs if e["event"] == "permissions_computed"]
        assert len(events) == 1
        assert events[0]["user_id"] == 2
        assert events[0]["privileges"] == expected

    async def test_emits_log_for_no_roles(self) -> None:
        """roleのないuserでもpermissions_computed logを出す契約を検証する.

        Returns:
            None: Privileges.NONEと対応logを検証して完了し,呼び出し側へ値を返さない.
        """
        svc, _repo = _make_service()

        with capture_logs() as cap_logs:
            result = await svc.compute_permissions(user_id=999)

        assert result == Privileges.NONE
        events = [e for e in cap_logs if e["event"] == "permissions_computed"]
        assert len(events) == 1
        assert events[0]["user_id"] == 999
        assert events[0]["privileges"] == Privileges.NONE


# ── compute_session_authorization ──────────────────────────────────────


class TestComputeSessionAuthorizationNoRole:
    """role未割当userのSessionAuthorization snapshot契約を検証する."""

    async def test_no_roles_returns_empty_snapshot(self) -> None:
        """roleのないuserに空role IDとPrivileges.NONEを返す契約を検証する.

        Returns:
            None: 空snapshotのPrivilegesとrole IDを検証して完了し,呼び出し側へ値を返さない.
        """
        svc, _repo = _make_service()

        result = await svc.compute_session_authorization(user_id=999)

        assert result.privileges == Privileges.NONE
        assert result.role_ids == ()


class TestComputeSessionAuthorizationSingleRole:
    """単一roleのSessionAuthorization snapshot反映契約を検証する."""

    async def test_single_default_role(self) -> None:
        """Default roleのPrivilegesとrole IDをsnapshotへ反映する契約を検証する.

        Returns:
            None: default roleのsnapshot内容を検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)

        result = await svc.compute_session_authorization(user_id=1)

        assert result.privileges == ROLE_DEFAULT.permissions
        assert result.role_ids == (ROLE_DEFAULT.id,)

    async def test_single_moderator_role(self) -> None:
        """Moderator roleのPrivilegesとrole IDをsnapshotへ反映する契約を検証する.

        Returns:
            None: moderator roleのsnapshot内容を検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        await repo.assign_role(user_id=2, role_id=ROLE_MODERATOR.id)

        result = await svc.compute_session_authorization(user_id=2)

        assert result.privileges == Privileges.MODERATOR
        assert result.role_ids == (ROLE_MODERATOR.id,)


class TestComputeSessionAuthorizationMultipleRoles:
    """複数roleのSessionAuthorization snapshot集約契約を検証する."""

    async def test_default_plus_supporter(self) -> None:
        """defaultとsupporterのPrivilegesおよびrole IDを集約する契約を検証する.

        Returns:
            None: 2つのroleによるsnapshot内容を検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)
        await repo.assign_role(user_id=1, role_id=ROLE_SUPPORTER.id)

        result = await svc.compute_session_authorization(user_id=1)

        expected_privs = ROLE_DEFAULT.permissions | Privileges.SUPPORTER
        assert result.privileges == expected_privs
        assert set(result.role_ids) == {ROLE_DEFAULT.id, ROLE_SUPPORTER.id}

    async def test_all_roles_combined(self) -> None:
        """全seed roleのPrivilegesおよびrole IDを集約する契約を検証する.

        Returns:
            None: 全roleによるsnapshot内容を検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        for role in ALL_ROLES:
            await repo.assign_role(user_id=1, role_id=role.id)

        result = await svc.compute_session_authorization(user_id=1)

        expected_privs = Privileges.NONE
        for role in ALL_ROLES:
            expected_privs |= role.permissions
        assert result.privileges == expected_privs
        assert set(result.role_ids) == {r.id for r in ALL_ROLES}

    async def test_moderator_plus_admin(self) -> None:
        """moderatorとadminのPrivilegesおよびrole IDを集約する契約を検証する.

        Returns:
            None: 管理roleによるsnapshot内容を検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        await repo.assign_role(user_id=3, role_id=ROLE_MODERATOR.id)
        await repo.assign_role(user_id=3, role_id=ROLE_ADMIN.id)

        result = await svc.compute_session_authorization(user_id=3)

        assert result.privileges == (Privileges.MODERATOR | Privileges.ADMIN)
        assert set(result.role_ids) == {ROLE_MODERATOR.id, ROLE_ADMIN.id}


class TestComputeSessionAuthorizationRoleOrdering:
    """SessionAuthorizationのrole ID順序保持契約を検証する."""

    async def test_role_ids_in_position_order(self) -> None:
        """割当順ではなくrole position昇順でrole IDを返す契約を検証する.

        Returns:
            None: position順のrole ID列を検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        # Assign in reverse position order
        await repo.assign_role(user_id=1, role_id=ROLE_ADMIN.id)  # position=3
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)  # position=0
        await repo.assign_role(user_id=1, role_id=ROLE_MODERATOR.id)  # position=2

        result = await svc.compute_session_authorization(user_id=1)

        # get_roles_for_user returns sorted by position ascending
        assert result.role_ids == (ROLE_DEFAULT.id, ROLE_MODERATOR.id, ROLE_ADMIN.id)


class TestComputeSessionAuthorizationSnapshotType:
    """SessionAuthorizationの戻り値型契約を検証する."""

    async def test_returns_session_authorization_instance(self) -> None:
        """計算結果がSessionAuthorization instanceである契約を検証する.

        Returns:
            None: 戻り値のinstance型を検証して完了し,呼び出し側へ値を返さない.
        """
        svc, repo = _make_service()
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)

        result = await svc.compute_session_authorization(user_id=1)

        assert isinstance(result, SessionAuthorization)
