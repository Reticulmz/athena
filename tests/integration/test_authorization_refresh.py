"""In-memory authorization refreshがactive sessionへ反映されるcontractを検証する.

Notes:
    Role変更後のrefreshとsession保持をin-memory repository/storeで検証する.
"""

from __future__ import annotations

import pytest

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import AuthorizationRefreshStatus, SessionData
from osu_server.repositories.memory.commands.roles import InMemoryRoleCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.roles import InMemoryRoleQueryRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
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
    InMemoryRoleCommandRepository,
]:
    """Authorization refresh integration test用のin-memory dependency群を構築する.

    Returns:
        tuple: service, session store, role command repositoryの順のtest dependency.

    Notes:
        全roleをseedし, command/query repositoryが同一in-memory stateを共有する.
    """
    state = InMemoryCommandRepositoryState()
    uow_factory = InMemoryUnitOfWorkFactory(state)
    role_repo = InMemoryRoleCommandRepository(state)
    role_query_repo = InMemoryRoleQueryRepository(uow_factory)
    for role in ALL_ROLES:
        role_repo.add_role(role)
    session_store = InMemorySessionStore()
    permission_service = PermissionService(role_repo=role_query_repo)
    service = SessionAuthorizationService(
        permission_service=permission_service,
        session_store=session_store,
        role_repository=role_query_repo,
    )
    return service, session_store, role_repo


_DEFAULT_PRIVILEGES = int(Privileges.NORMAL | Privileges.UNRESTRICTED)


def _make_session(
    user_id: int = 1,
    username: str = "test",
    privileges: int = _DEFAULT_PRIVILEGES,
    role_ids: tuple[int, ...] = (1,),
) -> SessionData:
    """Authorization refresh test用のactive session dataを構築する.

    Args:
        user_id (int): sessionを所有するtest user ID.
        username (str): sessionに保存するdisplay name.
        privileges (int): refresh前のserver-side privilege bitmask.
        role_ids (tuple[int, ...]): refresh前のassigned role ID列.

    Returns:
        SessionData: Japan client metadataと指定authorizationを持つsession data.
    """
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
    """Role変更後のrefreshがactive session authorizationを更新するcontractを検証する."""

    @pytest.mark.asyncio
    async def test_role_permission_change_updates_session_authorization(self) -> None:
        """Role permission変更後のrefreshがsession privilegeを更新するcontractを検証する.

        Returns:
            None: active sessionが変更後のrole privilegeを持つことを確認して完了する.
        """
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
        """Role grant後のuser refreshがsession roleとprivilegeを更新するcontractを検証する.

        Returns:
            None: active sessionが新しいrole IDとcombined privilegeを持つことを確認する.
        """
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
        """Role revoke後のrefreshがsessionからrevoke済みprivilegeを除去するcontractを検証する.

        Returns:
            None: re-loginなしでgranted privilegeをrevokeできることを確認して完了する.

        Notes:
            Grantとrevokeを連続して適用するequivalent ACL transitionを検証する.
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

        await repo.set_roles_for_user(user_id=1, role_ids=(ROLE_DEFAULT.id,))

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
        """Authorization refreshがsessionのnon-authorization fieldを保持するcontractを検証する.

        Returns:
            None: privilege更新後もprofileとclient metadataが不変であることを確認する.
        """
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
    """Authorization refreshがsessionを無効化しないcontractを検証する."""

    @pytest.mark.asyncio
    async def test_refresh_preserves_session_existence(self) -> None:
        """Authorization refresh後もsession tokenが有効なままであるcontractを検証する.

        Returns:
            None: refresh前後でsession existenceとuser lookupが保持されることを確認する.
        """
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
        """Logout pathのdelete_by_userがsessionを削除するcontractを検証する.

        Returns:
            None: tokenとuser lookupの両方が削除されることを確認して完了する.
        """
        store = InMemorySessionStore()
        await store.create(user_id=1, token="token-abc", data=_make_session())

        assert await store.exists("token-abc") is True

        await store.delete_by_user(user_id=1)

        assert await store.exists("token-abc") is False
        assert await store.get_by_user(user_id=1) is None

    @pytest.mark.asyncio
    async def test_no_active_session_returns_no_active(self) -> None:
        """Active sessionがないuserのrefreshがNO_ACTIVE_SESSIONを返すcontractを検証する.

        Returns:
            None: refreshがnew sessionを作成せずstatusだけを返すことを確認して完了する.
        """
        svc, store, repo = _make_services()

        await repo.assign_role(user_id=1, role_id=ROLE_DEFAULT.id)
        # No session created

        result = await svc.refresh_user_authorization(user_id=1)
        assert result.status == AuthorizationRefreshStatus.NO_ACTIVE_SESSION
        assert result.authorization is None

        # No session was created
        assert await store.get_by_user(user_id=1) is None
        assert await store.list_active_sessions() == []
