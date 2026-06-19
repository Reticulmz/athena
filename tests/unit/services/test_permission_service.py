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
    _uow_factory: InMemoryUnitOfWorkFactory

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def assign_role(self, *, user_id: int, role_id: int) -> None:
        async with self._uow_factory() as uow:
            await uow.roles.assign_role(user_id=user_id, role_id=role_id)
            await uow.commit()


def _make_service(
    roles: list[Role] | None = None,
) -> tuple[PermissionService, RoleAssignmentHarness]:
    uow_factory = InMemoryUnitOfWorkFactory()
    uow_factory.seed_roles(roles or ALL_ROLES)
    repo = InMemoryRoleQueryRepository(uow_factory)
    return PermissionService(role_repo=repo), RoleAssignmentHarness(uow_factory)


# ── compute_permissions ──────────────────────────────────────────────


class TestComputePermissionsSingleRole:
    """単一ロールの permissions がそのまま返される。"""

    async def test_single_default_role(self) -> None:
        svc, repo = _make_service()
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)

        result = await svc.compute_permissions(user_id=1)

        assert result == ROLE_DEFAULT.permissions

    async def test_single_supporter_role(self) -> None:
        svc, repo = _make_service()
        await repo.assign_role(user_id=2, role_id=ROLE_SUPPORTER.id)

        result = await svc.compute_permissions(user_id=2)

        assert result == Privileges.SUPPORTER


class TestComputePermissionsMultipleRoles:
    """複数ロールの permissions が OR 結合される。"""

    async def test_default_plus_supporter(self) -> None:
        svc, repo = _make_service()
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)
        await repo.assign_role(user_id=1, role_id=ROLE_SUPPORTER.id)

        result = await svc.compute_permissions(user_id=1)

        expected = ROLE_DEFAULT.permissions | Privileges.SUPPORTER
        assert result == expected

    async def test_all_roles_combined(self) -> None:
        svc, repo = _make_service()
        for role in ALL_ROLES:
            await repo.assign_role(user_id=1, role_id=role.id)

        result = await svc.compute_permissions(user_id=1)

        expected = Privileges.NONE
        for role in ALL_ROLES:
            expected |= role.permissions
        assert result == expected

    async def test_moderator_plus_admin(self) -> None:
        svc, repo = _make_service()
        await repo.assign_role(user_id=3, role_id=ROLE_MODERATOR.id)
        await repo.assign_role(user_id=3, role_id=ROLE_ADMIN.id)

        result = await svc.compute_permissions(user_id=3)

        assert result == (Privileges.MODERATOR | Privileges.ADMIN)


class TestComputePermissionsNoRoles:
    """ロールなしのユーザーは Privileges.NONE を返す。"""

    async def test_no_roles_returns_none(self) -> None:
        svc, _repo = _make_service()

        result = await svc.compute_permissions(user_id=999)

        assert result == Privileges.NONE


# ── permissions_computed ログイベント ────────────────────────────────


class TestPermissionsComputedLog:
    """compute_permissions() の permissions_computed ログイベント検証。"""

    async def test_emits_log_with_user_id_and_privileges(self) -> None:
        """計算完了時に user_id と privileges を含むログが出力される。"""
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
        """複数ロールの OR 結合結果がログに含まれる。"""
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
        """ロールなしユーザーでも permissions_computed が出力される。"""
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
    """ロールなしユーザーは NONE 権限と空 role_ids の snapshot を返す。"""

    async def test_no_roles_returns_empty_snapshot(self) -> None:
        svc, _repo = _make_service()

        result = await svc.compute_session_authorization(user_id=999)

        assert result.privileges == Privileges.NONE
        assert result.role_ids == ()


class TestComputeSessionAuthorizationSingleRole:
    """単一ロールの権限と role_id が snapshot に反映される。"""

    async def test_single_default_role(self) -> None:
        svc, repo = _make_service()
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)

        result = await svc.compute_session_authorization(user_id=1)

        assert result.privileges == ROLE_DEFAULT.permissions
        assert result.role_ids == (ROLE_DEFAULT.id,)

    async def test_single_moderator_role(self) -> None:
        svc, repo = _make_service()
        await repo.assign_role(user_id=2, role_id=ROLE_MODERATOR.id)

        result = await svc.compute_session_authorization(user_id=2)

        assert result.privileges == Privileges.MODERATOR
        assert result.role_ids == (ROLE_MODERATOR.id,)


class TestComputeSessionAuthorizationMultipleRoles:
    """複数ロールで permission OR と全 role_id を含む snapshot。"""

    async def test_default_plus_supporter(self) -> None:
        svc, repo = _make_service()
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)
        await repo.assign_role(user_id=1, role_id=ROLE_SUPPORTER.id)

        result = await svc.compute_session_authorization(user_id=1)

        expected_privs = ROLE_DEFAULT.permissions | Privileges.SUPPORTER
        assert result.privileges == expected_privs
        assert set(result.role_ids) == {ROLE_DEFAULT.id, ROLE_SUPPORTER.id}

    async def test_all_roles_combined(self) -> None:
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
        svc, repo = _make_service()
        await repo.assign_role(user_id=3, role_id=ROLE_MODERATOR.id)
        await repo.assign_role(user_id=3, role_id=ROLE_ADMIN.id)

        result = await svc.compute_session_authorization(user_id=3)

        assert result.privileges == (Privileges.MODERATOR | Privileges.ADMIN)
        assert set(result.role_ids) == {ROLE_MODERATOR.id, ROLE_ADMIN.id}


class TestComputeSessionAuthorizationRoleOrdering:
    """role_ids は get_roles_for_user の返す位置順を保持する。"""

    async def test_role_ids_in_position_order(self) -> None:
        svc, repo = _make_service()
        # Assign in reverse position order
        await repo.assign_role(user_id=1, role_id=ROLE_ADMIN.id)  # position=3
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)  # position=0
        await repo.assign_role(user_id=1, role_id=ROLE_MODERATOR.id)  # position=2

        result = await svc.compute_session_authorization(user_id=1)

        # get_roles_for_user returns sorted by position ascending
        assert result.role_ids == (ROLE_DEFAULT.id, ROLE_MODERATOR.id, ROLE_ADMIN.id)


class TestComputeSessionAuthorizationSnapshotType:
    """戻り値は SessionAuthorization の frozen dataclass。"""

    async def test_returns_session_authorization_instance(self) -> None:
        svc, repo = _make_service()
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)

        result = await svc.compute_session_authorization(user_id=1)

        assert isinstance(result, SessionAuthorization)
