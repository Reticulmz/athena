"""session authorizationを更新するcommand use-caseを提供する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.sessions import (
        RoleAuthorizationRefreshResult,
        UserAuthorizationRefreshResult,
    )


class _SessionAuthorizationService(Protocol):
    """ユーザーまたはrole単位のsession authorization更新を提供するserviceを定義する."""

    async def refresh_user_authorization(
        self,
        user_id: int,
    ) -> UserAuthorizationRefreshResult:
        """一人のユーザーのactive session authorizationを更新する.

        Args:
            user_id (int): authorizationを更新するユーザーID.

        Returns:
            UserAuthorizationRefreshResult: 更新、session不在、または計算失敗を表す結果.
        """
        ...

    async def refresh_role_authorization(
        self,
        role_id: int,
    ) -> RoleAuthorizationRefreshResult:
        """一つのroleに属するユーザーのsession authorizationを更新する.

        Args:
            role_id (int): 対象ユーザーを検索するrole ID.

        Returns:
            RoleAuthorizationRefreshResult: 対象ユーザーごとの更新結果を集約した結果.
        """
        ...


@dataclass(slots=True, frozen=True)
class RefreshUserAuthorizationCommandInput:
    """一人のユーザーのauthorization更新command入力を表す.

    Attributes:
        user_id (int): authorizationを更新するユーザーID.
    """

    user_id: int


@dataclass(slots=True, frozen=True)
class RefreshUserAuthorizationCommandResult:
    """一人のユーザーのauthorization更新command結果を表す.

    Attributes:
        outcome (UserAuthorizationRefreshResult): authorization更新の成否を表す結果.
    """

    outcome: UserAuthorizationRefreshResult


class RefreshUserAuthorizationCommand(Protocol):
    """一人のユーザーのauthorization更新workflowを表すcommand boundaryを定義する."""

    async def execute(
        self,
        input_data: RefreshUserAuthorizationCommandInput,
    ) -> RefreshUserAuthorizationCommandResult:
        """指定ユーザーのauthorization更新commandを実行する.

        Args:
            input_data (RefreshUserAuthorizationCommandInput): 更新対象ユーザーのID.

        Returns:
            RefreshUserAuthorizationCommandResult: authorization更新の結果.
        """
        ...


class RefreshUserAuthorizationCommandUseCase:
    """一人のactive userのsession authorization snapshotを更新する.

    Attributes:
        _session_authorization_service (_SessionAuthorizationService): authorization更新service.
    """

    _session_authorization_service: _SessionAuthorizationService

    def __init__(self, *, session_authorization_service: _SessionAuthorizationService) -> None:
        """ユーザーauthorizationを更新するserviceを初期化する.

        Args:
            session_authorization_service (_SessionAuthorizationService): authorization更新service.

        """
        self._session_authorization_service = session_authorization_service

    async def execute(
        self,
        input_data: RefreshUserAuthorizationCommandInput,
    ) -> RefreshUserAuthorizationCommandResult:
        """指定ユーザーのauthorization更新をserviceへ委譲する.

        Args:
            input_data (RefreshUserAuthorizationCommandInput): 更新対象ユーザーのID.

        Returns:
            RefreshUserAuthorizationCommandResult: serviceの更新結果を保持するcommand result.
        """
        outcome = await self._session_authorization_service.refresh_user_authorization(
            input_data.user_id,
        )
        return RefreshUserAuthorizationCommandResult(outcome=outcome)


@dataclass(slots=True, frozen=True)
class RefreshRoleAuthorizationCommandInput:
    """role単位のauthorization更新command入力を表す.

    Attributes:
        role_id (int): 対象ユーザーを検索するrole ID.
    """

    role_id: int


@dataclass(slots=True, frozen=True)
class RefreshRoleAuthorizationCommandResult:
    """role単位のauthorization更新command結果を表す.

    Attributes:
        outcome (RoleAuthorizationRefreshResult): role所属ユーザーごとの更新結果.
    """

    outcome: RoleAuthorizationRefreshResult


class RefreshRoleAuthorizationCommand(Protocol):
    """role単位のauthorization更新workflowを表すcommand boundaryを定義する."""

    async def execute(
        self,
        input_data: RefreshRoleAuthorizationCommandInput,
    ) -> RefreshRoleAuthorizationCommandResult:
        """指定roleのauthorization更新commandを実行する.

        Args:
            input_data (RefreshRoleAuthorizationCommandInput): 対象roleのID.

        Returns:
            RefreshRoleAuthorizationCommandResult: role所属ユーザーごとの更新結果.
        """
        ...


class RefreshRoleAuthorizationCommandUseCase:
    """一つのroleに属するユーザーのsession authorization snapshotを更新する.

    Attributes:
        _session_authorization_service (_SessionAuthorizationService): authorization更新service.
    """

    _session_authorization_service: _SessionAuthorizationService

    def __init__(self, *, session_authorization_service: _SessionAuthorizationService) -> None:
        """Role authorizationを更新するserviceを初期化する.

        Args:
            session_authorization_service (_SessionAuthorizationService): authorization更新service.

        """
        self._session_authorization_service = session_authorization_service

    async def execute(
        self,
        input_data: RefreshRoleAuthorizationCommandInput,
    ) -> RefreshRoleAuthorizationCommandResult:
        """指定roleのauthorization更新をserviceへ委譲する.

        Args:
            input_data (RefreshRoleAuthorizationCommandInput): 対象roleのID.

        Returns:
            RefreshRoleAuthorizationCommandResult: serviceの更新結果を保持するcommand result.
        """
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
