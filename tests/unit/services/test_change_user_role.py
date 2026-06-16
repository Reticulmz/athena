"""Tests for the change user role command use-case."""

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
    uow_factory = InMemoryUnitOfWorkFactory()
    uow_factory.seed_roles([_DEFAULT_ROLE, _MODERATOR_ROLE, _ADMIN_ROLE])
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


def _make_session(
    *,
    user_id: int,
    privileges: Privileges,
    role_ids: tuple[int, ...],
) -> SessionData:
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


async def test_change_user_role_refreshes_session_for_existing_single_role() -> None:
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
    use_case, _, _ = _make_use_case()

    result = await use_case.execute(
        ChangeUserRoleCommandInput(
            username="MissingUser",
            role_name="Admin",
        )
    )

    assert result.status is ChangeUserRoleStatus.USER_NOT_FOUND


async def test_change_user_role_returns_role_not_found_without_changing_roles() -> None:
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
