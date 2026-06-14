"""Session authorization refresh command use-cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.sessions import (
        RoleAuthorizationRefreshResult,
        UserAuthorizationRefreshResult,
    )


class _SessionAuthorizationService(Protocol):
    async def refresh_user_authorization(
        self,
        user_id: int,
    ) -> UserAuthorizationRefreshResult: ...

    async def refresh_role_authorization(
        self,
        role_id: int,
    ) -> RoleAuthorizationRefreshResult: ...


@dataclass(slots=True, frozen=True)
class RefreshUserAuthorizationCommandInput:
    user_id: int


@dataclass(slots=True, frozen=True)
class RefreshUserAuthorizationCommandResult:
    outcome: UserAuthorizationRefreshResult


class RefreshUserAuthorizationCommand(Protocol):
    async def execute(
        self,
        input_data: RefreshUserAuthorizationCommandInput,
    ) -> RefreshUserAuthorizationCommandResult: ...


class RefreshUserAuthorizationCommandUseCase:
    """Refresh one active user's session authorization snapshot."""

    _session_authorization_service: _SessionAuthorizationService

    def __init__(self, *, session_authorization_service: _SessionAuthorizationService) -> None:
        self._session_authorization_service = session_authorization_service

    async def execute(
        self,
        input_data: RefreshUserAuthorizationCommandInput,
    ) -> RefreshUserAuthorizationCommandResult:
        outcome = await self._session_authorization_service.refresh_user_authorization(
            input_data.user_id,
        )
        return RefreshUserAuthorizationCommandResult(outcome=outcome)


@dataclass(slots=True, frozen=True)
class RefreshRoleAuthorizationCommandInput:
    role_id: int


@dataclass(slots=True, frozen=True)
class RefreshRoleAuthorizationCommandResult:
    outcome: RoleAuthorizationRefreshResult


class RefreshRoleAuthorizationCommand(Protocol):
    async def execute(
        self,
        input_data: RefreshRoleAuthorizationCommandInput,
    ) -> RefreshRoleAuthorizationCommandResult: ...


class RefreshRoleAuthorizationCommandUseCase:
    """Refresh session authorization snapshots for users assigned to one role."""

    _session_authorization_service: _SessionAuthorizationService

    def __init__(self, *, session_authorization_service: _SessionAuthorizationService) -> None:
        self._session_authorization_service = session_authorization_service

    async def execute(
        self,
        input_data: RefreshRoleAuthorizationCommandInput,
    ) -> RefreshRoleAuthorizationCommandResult:
        outcome = await self._session_authorization_service.refresh_role_authorization(
            input_data.role_id,
        )
        return RefreshRoleAuthorizationCommandResult(outcome=outcome)


__all__ = [
    "RefreshRoleAuthorizationCommand",
    "RefreshRoleAuthorizationCommandInput",
    "RefreshRoleAuthorizationCommandResult",
    "RefreshRoleAuthorizationCommandUseCase",
    "RefreshUserAuthorizationCommand",
    "RefreshUserAuthorizationCommandInput",
    "RefreshUserAuthorizationCommandResult",
    "RefreshUserAuthorizationCommandUseCase",
]
