"""Change user role command use-case."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.identity.system_users import BANCHO_BOT_USER_ID
from osu_server.domain.identity.users import User

if TYPE_CHECKING:
    from osu_server.domain.identity.sessions import (
        AuthorizationRefreshStatus,
        UserAuthorizationRefreshResult,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory


class _SessionAuthorizationRefreshService(Protocol):
    async def refresh_user_authorization(
        self,
        user_id: int,
    ) -> UserAuthorizationRefreshResult: ...


class ChangeUserRoleStatus(StrEnum):
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    USER_NOT_FOUND = "user_not_found"
    ROLE_NOT_FOUND = "role_not_found"
    SYSTEM_USER_DENIED = "system_user_denied"


@dataclass(slots=True, frozen=True)
class ChangeUserRoleCommandInput:
    username: str
    role_name: str


@dataclass(slots=True, frozen=True)
class ChangeUserRoleCommandResult:
    status: ChangeUserRoleStatus
    username: str
    role_name: str
    user_id: int | None = None
    role_id: int | None = None
    previous_role_names: tuple[str, ...] = ()
    authorization_refresh_status: AuthorizationRefreshStatus | None = None

    @property
    def changed(self) -> bool:
        return self.status is ChangeUserRoleStatus.CHANGED


class ChangeUserRoleCommand(Protocol):
    async def execute(
        self,
        input_data: ChangeUserRoleCommandInput,
    ) -> ChangeUserRoleCommandResult: ...


class ChangeUserRoleCommandUseCase:
    """Replace a user's assigned roles with one target role."""

    _uow_factory: UnitOfWorkFactory
    _session_authorization_service: _SessionAuthorizationRefreshService
    _system_user_id: int

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        session_authorization_service: _SessionAuthorizationRefreshService,
        system_user_id: int = BANCHO_BOT_USER_ID,
    ) -> None:
        self._uow_factory = uow_factory
        self._session_authorization_service = session_authorization_service
        self._system_user_id = system_user_id

    async def execute(
        self,
        input_data: ChangeUserRoleCommandInput,
    ) -> ChangeUserRoleCommandResult:
        safe_username = User.normalize_username(input_data.username)
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_safe_username(safe_username)
            if user is None:
                return ChangeUserRoleCommandResult(
                    status=ChangeUserRoleStatus.USER_NOT_FOUND,
                    username=input_data.username,
                    role_name=input_data.role_name,
                )

            if user.id == self._system_user_id:
                return ChangeUserRoleCommandResult(
                    status=ChangeUserRoleStatus.SYSTEM_USER_DENIED,
                    username=user.username,
                    user_id=user.id,
                    role_name=input_data.role_name,
                )

            target_role = await uow.roles.get_by_name(input_data.role_name)
            if target_role is None:
                return ChangeUserRoleCommandResult(
                    status=ChangeUserRoleStatus.ROLE_NOT_FOUND,
                    username=user.username,
                    user_id=user.id,
                    role_name=input_data.role_name,
                )

            current_roles = await uow.roles.get_roles_for_user(user.id)
            current_role_ids = tuple(role.id for role in current_roles)
            previous_role_names = tuple(role.name for role in current_roles)
            if current_role_ids == (target_role.id,):
                status = ChangeUserRoleStatus.UNCHANGED
            else:
                await uow.roles.set_roles_for_user(user.id, (target_role.id,))
                await uow.commit()
                status = ChangeUserRoleStatus.CHANGED

        refresh_result = await self._session_authorization_service.refresh_user_authorization(
            user.id
        )

        return ChangeUserRoleCommandResult(
            status=status,
            username=user.username,
            user_id=user.id,
            role_name=target_role.name,
            role_id=target_role.id,
            previous_role_names=previous_role_names,
            authorization_refresh_status=refresh_result.status,
        )


__all__ = [
    "ChangeUserRoleCommand",
    "ChangeUserRoleCommandInput",
    "ChangeUserRoleCommandResult",
    "ChangeUserRoleCommandUseCase",
    "ChangeUserRoleStatus",
]
