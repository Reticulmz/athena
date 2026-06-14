"""Identity authorization query use-case boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.authorization import Privileges
    from osu_server.domain.identity.sessions import SessionAuthorization


class _PermissionService(Protocol):
    async def compute_permissions(self, user_id: int) -> Privileges: ...

    async def compute_session_authorization(self, user_id: int) -> SessionAuthorization: ...


@dataclass(slots=True, frozen=True)
class ComputePermissionsQueryInput:
    user_id: int


@dataclass(slots=True, frozen=True)
class ComputePermissionsQueryResult:
    privileges: Privileges


class ComputePermissionsQuery(Protocol):
    async def execute(
        self,
        input_data: ComputePermissionsQueryInput,
    ) -> ComputePermissionsQueryResult: ...


class ComputePermissionsQueryUseCase:
    """Read the role-derived server privileges for one user."""

    _permission_service: _PermissionService

    def __init__(self, *, permission_service: _PermissionService) -> None:
        self._permission_service = permission_service

    async def execute(
        self,
        input_data: ComputePermissionsQueryInput,
    ) -> ComputePermissionsQueryResult:
        privileges = await self._permission_service.compute_permissions(input_data.user_id)
        return ComputePermissionsQueryResult(privileges=privileges)


@dataclass(slots=True, frozen=True)
class ComputeSessionAuthorizationQueryInput:
    user_id: int


@dataclass(slots=True, frozen=True)
class ComputeSessionAuthorizationQueryResult:
    authorization: SessionAuthorization


class ComputeSessionAuthorizationQuery(Protocol):
    async def execute(
        self,
        input_data: ComputeSessionAuthorizationQueryInput,
    ) -> ComputeSessionAuthorizationQueryResult: ...


class ComputeSessionAuthorizationQueryUseCase:
    """Read the current role-derived session authorization snapshot."""

    _permission_service: _PermissionService

    def __init__(self, *, permission_service: _PermissionService) -> None:
        self._permission_service = permission_service

    async def execute(
        self,
        input_data: ComputeSessionAuthorizationQueryInput,
    ) -> ComputeSessionAuthorizationQueryResult:
        authorization = await self._permission_service.compute_session_authorization(
            input_data.user_id,
        )
        return ComputeSessionAuthorizationQueryResult(authorization=authorization)


__all__ = [
    "ComputePermissionsQuery",
    "ComputePermissionsQueryInput",
    "ComputePermissionsQueryResult",
    "ComputePermissionsQueryUseCase",
    "ComputeSessionAuthorizationQuery",
    "ComputeSessionAuthorizationQueryInput",
    "ComputeSessionAuthorizationQueryResult",
    "ComputeSessionAuthorizationQueryUseCase",
]
