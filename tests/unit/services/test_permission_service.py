from __future__ import annotations

from structlog.testing import capture_logs

from osu_server.domain.role import (
    ClientPermissions,
    Privileges,
    Role,
)
from osu_server.repositories.memory.role_repository import (
    InMemoryRoleRepository,
)
from osu_server.services.permission_service import PermissionService

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


def _make_service(
    roles: list[Role] | None = None,
) -> tuple[PermissionService, InMemoryRoleRepository]:
    repo = InMemoryRoleRepository(seed_roles=roles or ALL_ROLES)
    return PermissionService(role_repo=repo), repo


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


# ── to_client_flags ──────────────────────────────────────────────────


class TestToClientFlagsIndividual:
    """個別の Privileges フラグが正しい ClientPermissions にマッピングされる。"""

    def test_none_returns_normal(self) -> None:
        result = PermissionService.to_client_flags(Privileges.NONE)
        assert result == ClientPermissions.NORMAL

    def test_normal_returns_normal(self) -> None:
        result = PermissionService.to_client_flags(Privileges.NORMAL)
        assert result == ClientPermissions.NORMAL

    def test_moderator(self) -> None:
        result = PermissionService.to_client_flags(Privileges.MODERATOR)
        assert result == (ClientPermissions.NORMAL | ClientPermissions.MODERATOR)

    def test_supporter(self) -> None:
        result = PermissionService.to_client_flags(Privileges.SUPPORTER)
        assert result == (ClientPermissions.NORMAL | ClientPermissions.SUPPORTER)

    def test_admin(self) -> None:
        result = PermissionService.to_client_flags(Privileges.ADMIN)
        assert result == (ClientPermissions.NORMAL | ClientPermissions.PEPPY)

    def test_developer(self) -> None:
        result = PermissionService.to_client_flags(Privileges.DEVELOPER)
        assert result == (ClientPermissions.NORMAL | ClientPermissions.DEVELOPER)


class TestToClientFlagsCombinations:
    """複数の Privileges フラグが OR 結合で正しく変換される。"""

    def test_moderator_and_supporter(self) -> None:
        privs = Privileges.MODERATOR | Privileges.SUPPORTER
        result = PermissionService.to_client_flags(privs)
        expected = (
            ClientPermissions.NORMAL | ClientPermissions.MODERATOR | ClientPermissions.SUPPORTER
        )
        assert result == expected

    def test_all_mapped_flags(self) -> None:
        privs = (
            Privileges.MODERATOR | Privileges.SUPPORTER | Privileges.ADMIN | Privileges.DEVELOPER
        )
        result = PermissionService.to_client_flags(privs)
        expected = (
            ClientPermissions.NORMAL
            | ClientPermissions.MODERATOR
            | ClientPermissions.SUPPORTER
            | ClientPermissions.PEPPY
            | ClientPermissions.DEVELOPER
        )
        assert result == expected

    def test_admin_and_developer(self) -> None:
        privs = Privileges.ADMIN | Privileges.DEVELOPER
        result = PermissionService.to_client_flags(privs)
        expected = ClientPermissions.NORMAL | ClientPermissions.PEPPY | ClientPermissions.DEVELOPER
        assert result == expected

    def test_unmapped_flags_ignored(self) -> None:
        """VERIFIED, TOURNAMENT, UNRESTRICTED はクライアントフラグに影響しない。"""
        privs = Privileges.VERIFIED | Privileges.TOURNAMENT | Privileges.UNRESTRICTED
        result = PermissionService.to_client_flags(privs)
        assert result == ClientPermissions.NORMAL

    def test_full_privileges_set(self) -> None:
        """全 Privileges フラグを立てた場合のクライアント変換。"""
        all_privs = Privileges.NONE
        for p in Privileges:
            all_privs |= p
        result = PermissionService.to_client_flags(all_privs)
        expected = (
            ClientPermissions.NORMAL
            | ClientPermissions.MODERATOR
            | ClientPermissions.SUPPORTER
            | ClientPermissions.PEPPY
            | ClientPermissions.DEVELOPER
        )
        assert result == expected


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
        assert events[0]["user_id"] == 2  # noqa: PLR2004
        assert events[0]["privileges"] == expected

    async def test_emits_log_for_no_roles(self) -> None:
        """ロールなしユーザーでも permissions_computed が出力される。"""
        svc, _repo = _make_service()

        with capture_logs() as cap_logs:
            result = await svc.compute_permissions(user_id=999)

        assert result == Privileges.NONE
        events = [e for e in cap_logs if e["event"] == "permissions_computed"]
        assert len(events) == 1
        assert events[0]["user_id"] == 999  # noqa: PLR2004
        assert events[0]["privileges"] == Privileges.NONE
