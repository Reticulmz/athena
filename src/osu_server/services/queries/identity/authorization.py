"""Identity authorizationのread-only query boundaryを定義するmodule.

role由来のPrivilegesとSessionAuthorization snapshotをquery input/resultへ変換する.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.authorization import Privileges
    from osu_server.domain.identity.sessions import SessionAuthorization


class _PermissionService(Protocol):
    """role由来の権限情報を計算するservice protocolを表す.

    このprotocolはquery use-caseが必要とするread-only操作だけを公開する.
    """

    async def compute_permissions(self, user_id: int) -> Privileges:
        """指定userのrole由来Privilegesを計算する.

        Args:
            user_id (int): 権限を計算するuserの識別子.

        Returns:
            Privileges: userに割り当てられたroleをOR結合したserver-side権限.
        """
        ...

    async def compute_session_authorization(self, user_id: int) -> SessionAuthorization:
        """指定userのsession authorization snapshotを計算する.

        Args:
            user_id (int): authorizationを計算するuserの識別子.

        Returns:
            SessionAuthorization: 同じrole集合から導出したPrivilegesとrole ID群のsnapshot.
        """
        ...


@dataclass(slots=True, frozen=True)
class ComputePermissionsQueryInput:
    """単一userのPrivilegesを読むquery inputを表す.

    Attributes:
        user_id (int): role由来の権限を取得するuserの識別子.
    """

    user_id: int


@dataclass(slots=True, frozen=True)
class ComputePermissionsQueryResult:
    """単一userのPrivileges query結果を表す.

    Attributes:
        privileges (Privileges): userに割り当てられたroleから導出したserver-side権限.
    """

    privileges: Privileges


class ComputePermissionsQuery(Protocol):
    """単一userのrole由来Privilegesを取得するquery protocolを表す."""

    async def execute(
        self,
        input_data: ComputePermissionsQueryInput,
    ) -> ComputePermissionsQueryResult:
        """指定inputに対応するPrivileges query結果を返す.

        Args:
            input_data (ComputePermissionsQueryInput): 対象userを指定するquery input.

        Returns:
            ComputePermissionsQueryResult: role由来Privilegesを含むquery結果.
        """
        ...


class ComputePermissionsQueryUseCase:
    """単一userのrole由来server-side権限を読むquery use-caseを表す.

    Attributes:
        _permission_service (_PermissionService): role集合からPrivilegesを導出するread service.
    """

    _permission_service: _PermissionService

    def __init__(self, *, permission_service: _PermissionService) -> None:
        """Privilegesを計算するread serviceを設定する.

        Args:
            permission_service (_PermissionService): role由来のPrivilegesを計算するservice.
        """
        self._permission_service = permission_service

    async def execute(
        self,
        input_data: ComputePermissionsQueryInput,
    ) -> ComputePermissionsQueryResult:
        """指定userのPrivilegesをread-onlyで取得する.

        Args:
            input_data (ComputePermissionsQueryInput): 対象userを指定するquery input.

        Returns:
            ComputePermissionsQueryResult: role由来のserver-side権限を含む結果.
        """
        privileges = await self._permission_service.compute_permissions(input_data.user_id)
        return ComputePermissionsQueryResult(privileges=privileges)


@dataclass(slots=True, frozen=True)
class ComputeSessionAuthorizationQueryInput:
    """単一userのsession authorizationを読むquery inputを表す.

    Attributes:
        user_id (int): authorization snapshotを取得するuserの識別子.
    """

    user_id: int


@dataclass(slots=True, frozen=True)
class ComputeSessionAuthorizationQueryResult:
    """単一userのsession authorization query結果を表す.

    Attributes:
        authorization (SessionAuthorization): role由来のPrivilegesとrole ID群を持つsnapshot.
    """

    authorization: SessionAuthorization


class ComputeSessionAuthorizationQuery(Protocol):
    """単一userのsession authorization snapshotを取得するquery protocolを表す."""

    async def execute(
        self,
        input_data: ComputeSessionAuthorizationQueryInput,
    ) -> ComputeSessionAuthorizationQueryResult:
        """指定inputに対応するsession authorization query結果を返す.

        Args:
            input_data (ComputeSessionAuthorizationQueryInput): 対象userを指定するquery input.

        Returns:
            ComputeSessionAuthorizationQueryResult: role由来authorization snapshotを含む結果.
        """
        ...


class ComputeSessionAuthorizationQueryUseCase:
    """単一userのrole由来session authorization snapshotを読むquery use-caseを表す.

    Attributes:
        _permission_service (_PermissionService): role集合からauthorizationを導出するread service.
    """

    _permission_service: _PermissionService

    def __init__(self, *, permission_service: _PermissionService) -> None:
        """SessionAuthorizationを計算するread serviceを設定する.

        Args:
            permission_service (_PermissionService): role由来authorizationを計算するservice.
        """
        self._permission_service = permission_service

    async def execute(
        self,
        input_data: ComputeSessionAuthorizationQueryInput,
    ) -> ComputeSessionAuthorizationQueryResult:
        """指定userのsession authorization snapshotをread-onlyで取得する.

        Args:
            input_data (ComputeSessionAuthorizationQueryInput): 対象userを指定するquery input.

        Returns:
            ComputeSessionAuthorizationQueryResult: role由来authorization snapshotを含む結果.
        """
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
