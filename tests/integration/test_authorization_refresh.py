"""Integration tests for authorization refresh — InMemory implementations.

Validates:
- Task 4.2: role change → refresh → subsequent action sees updated authorization
- Task 4.3: refresh does not delete sessions; logout still deletes sessions
"""

from __future__ import annotations

import pytest

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import AuthorizationRefreshStatus, SessionData
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.services.commands.identity.session_authorization_service import (
    SessionAuthorizationService,
)
from osu_server.services.queries.identity.permission_service import PermissionService

# ── Seed data ────────────────────────────────────────────────────────────

ROLE_DEFAULT = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
    position=0,
)
ROLE_MODERATOR = Role(
    id=2,
    name="Moderator",
    permissions=Privileges.MODERATOR,
    position=1,
)
ROLE_ADMIN = Role(
    id=3,
    name="Admin",
    permissions=Privileges.ADMIN,
    position=2,
)

ALL_ROLES = [ROLE_DEFAULT, ROLE_MODERATOR, ROLE_ADMIN]


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_services() -> tuple[
    SessionAuthorizationService,
    InMemorySessionStore,
    InMemoryRoleRepository,
]:
    """Create SessionAuthorizationService with InMemory implementations."""
    role_repo = InMemoryRoleRepository(seed_roles=ALL_ROLES)
    session_store = InMemorySessionStore()
    permission_service = PermissionService(role_repo=role_repo)
    service = SessionAuthorizationService(
        permission_service=permission_service,
        session_store=session_store,
        role_repository=role_repo,
    )
    return service, session_store, role_repo


_DEFAULT_PRIVILEGES = int(Privileges.NORMAL | Privileges.UNRESTRICTED)


def _make_session(
    user_id: int = 1,
    username: str = "test",
    privileges: int = _DEFAULT_PRIVILEGES,
    role_ids: tuple[int, ...] = (1,),
) -> SessionData:
    return SessionData(
        user_id=user_id,
        username=username,
        privileges=privileges,
        country="JP",
        osu_version="test",
        utc_offset=9,
        display_city=False,
        client_hashes="",
        pm_private=False,
        role_ids=role_ids,
    )


# ── Task 4.2: refreshed authorization in subsequent actions ─────────────


class TestRefreshedAuthorizationInSession:
    """Role 変更後に refresh すると session の認可が更新される。"""

    @pytest.mark.asyncio
    async def test_role_permission_change_updates_session_authorization(self) -> None:
        """role の permissions 変更 → refresh → session が新しい権限を反映する。"""
        svc, store, repo = _make_services()

        # Setup: user 1 has Default role, active session
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)
        await store.create(user_id=1, token="token-abc", data=_make_session())

        # Verify initial state
        session = await store.get_by_user(user_id=1)
        assert session is not None
        assert session.privileges == int(Privileges.NORMAL | Privileges.UNRESTRICTED)
        assert session.role_ids == (1,)

        # Change Default role permissions (add MODERATOR)
        repo.add_role(
            Role(
                id=ROLE_DEFAULT.id,
                name=ROLE_DEFAULT.name,
                permissions=ROLE_DEFAULT.permissions | Privileges.MODERATOR,
                position=ROLE_DEFAULT.position,
            )
        )

        # Refresh authorization for the role
        result = await svc.refresh_role_authorization(role_id=ROLE_DEFAULT.id)
        assert len(result.user_results) == 1
        assert result.user_results[0].status == AuthorizationRefreshStatus.REFRESHED

        # Session now has updated authorization
        session = await store.get_by_user(user_id=1)
        assert session is not None
        assert session.privileges == int(
            Privileges.NORMAL | Privileges.UNRESTRICTED | Privileges.MODERATOR
        )
        assert session.role_ids == (1,)

    @pytest.mark.asyncio
    async def test_new_role_grant_updates_session_after_refresh(self) -> None:
        """新しい role を付与 → refresh → session が追加された権限を反映する。"""
        svc, store, repo = _make_services()

        # Setup: user 1 has only Default role
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)
        await store.create(user_id=1, token="token-abc", data=_make_session())

        # Grant Admin role to user
        await repo.assign_role(user_id=1, role_id=ROLE_ADMIN.id)

        # Refresh user authorization
        result = await svc.refresh_user_authorization(user_id=1)
        assert result.status == AuthorizationRefreshStatus.REFRESHED

        # Session has combined permissions and both role IDs
        session = await store.get_by_user(user_id=1)
        assert session is not None
        assert session.privileges == int(
            Privileges.NORMAL | Privileges.UNRESTRICTED | Privileges.ADMIN
        )
        assert set(session.role_ids) == {1, 3}

    @pytest.mark.asyncio
    async def test_role_revoke_removes_permission_after_refresh(self) -> None:
        """role 剥奪 → refresh → session から該当権限が除去される。

        This is the "equivalent ACL transition" proving that access can be
        granted and then revoked without re-login.
        """
        svc, store, repo = _make_services()

        # Setup: user 1 has Default + Admin roles
        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)
        await repo.assign_role(user_id=1, role_id=ROLE_ADMIN.id)
        session_data = _make_session(
            privileges=int(Privileges.NORMAL | Privileges.UNRESTRICTED | Privileges.ADMIN),
            role_ids=(1, 3),
        )
        await store.create(user_id=1, token="token-abc", data=session_data)

        # Remove Admin role from user by clearing user_roles for that role
        # (Simulate role revoke: remove the user from the role's assignment)
        repo._user_roles[1] = {ROLE_DEFAULT.id}  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        # Refresh user authorization
        result = await svc.refresh_user_authorization(user_id=1)
        assert result.status == AuthorizationRefreshStatus.REFRESHED

        # Session has only Default permissions
        session = await store.get_by_user(user_id=1)
        assert session is not None
        assert session.privileges == int(Privileges.NORMAL | Privileges.UNRESTRICTED)
        assert session.role_ids == (1,)

    @pytest.mark.asyncio
    async def test_non_session_fields_preserved_after_refresh(self) -> None:
        """refresh 後も認可以外の session fields は保持される。"""
        svc, store, repo = _make_services()

        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)
        session_data = SessionData(
            user_id=1,
            username="preserved_user",
            privileges=int(Privileges.NORMAL),
            country="US",
            osu_version="b20240101",
            utc_offset=-5,
            display_city=True,
            client_hashes="h1:h2",
            pm_private=True,
            role_ids=(1,),
        )
        await store.create(user_id=1, token="token-abc", data=session_data)

        # Change role permissions
        repo.add_role(
            Role(
                id=ROLE_DEFAULT.id,
                name=ROLE_DEFAULT.name,
                permissions=ROLE_DEFAULT.permissions | Privileges.MODERATOR,
                position=ROLE_DEFAULT.position,
            )
        )

        _ = await svc.refresh_role_authorization(role_id=ROLE_DEFAULT.id)

        session = await store.get_by_user(user_id=1)
        assert session is not None
        # Authorization fields updated
        assert session.privileges == int(
            Privileges.NORMAL | Privileges.UNRESTRICTED | Privileges.MODERATOR
        )
        # Non-authorization fields preserved
        assert session.username == "preserved_user"
        assert session.country == "US"
        assert session.osu_version == "b20240101"
        assert session.utc_offset == -5
        assert session.display_city is True
        assert session.client_hashes == "h1:h2"
        assert session.pm_private is True


# ── Task 4.3: refresh does not invalidate session ───────────────────────


class TestRefreshDoesNotInvalidateSession:
    """refresh は session を削除せず、logout は session を削除する。"""

    @pytest.mark.asyncio
    async def test_refresh_preserves_session_existence(self) -> None:
        """refresh 後も session は存在し、token は有効。"""
        svc, store, repo = _make_services()

        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)
        await store.create(user_id=1, token="token-abc", data=_make_session())

        # Session exists before refresh
        assert await store.exists("token-abc") is True
        assert await store.get_by_user(user_id=1) is not None

        # Refresh
        result = await svc.refresh_user_authorization(user_id=1)
        assert result.status == AuthorizationRefreshStatus.REFRESHED

        # Session still exists after refresh — not deleted
        assert await store.exists("token-abc") is True
        assert await store.get_by_user(user_id=1) is not None

    @pytest.mark.asyncio
    async def test_delete_by_user_still_deletes_session(self) -> None:
        """delete_by_user は引き続き session を削除する (logout path)。"""
        store = InMemorySessionStore()
        await store.create(user_id=1, token="token-abc", data=_make_session())

        assert await store.exists("token-abc") is True

        await store.delete_by_user(user_id=1)

        assert await store.exists("token-abc") is False
        assert await store.get_by_user(user_id=1) is None

    @pytest.mark.asyncio
    async def test_no_active_session_returns_no_active(self) -> None:
        """session がない user の refresh は NO_ACTIVE_SESSION を返し、session を作成しない。"""
        svc, store, repo = _make_services()

        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)
        # No session created

        result = await svc.refresh_user_authorization(user_id=1)
        assert result.status == AuthorizationRefreshStatus.NO_ACTIVE_SESSION
        assert result.authorization is None

        # No session was created
        assert await store.get_by_user(user_id=1) is None
        assert await store.get_all_user_ids() == []
