"""session authorizationの更新をオーケストレーションするserviceを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

import structlog

from osu_server.domain.identity.sessions import (
    AuthorizationRefreshStatus,
    RoleAuthorizationRefreshResult,
    SessionAuthorization,
    UserAuthorizationRefreshResult,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.session_store import SessionAuthorizationRuntime


class _PermissionAuthorizationComputer(Protocol):
    """ユーザーの現在のroleからsession authorizationを計算する依存serviceを定義する."""

    async def compute_session_authorization(
        self,
        user_id: int,
    ) -> SessionAuthorization:
        """ユーザーの現在のroleとpermissionからauthorizationを計算する.

        Args:
            user_id (int): authorizationを計算するユーザーID.

        Returns:
            SessionAuthorization: active sessionへ適用するauthorization snapshot.
        """
        ...


class _RoleUserLookup(Protocol):
    """roleに属するユーザーを検索する依存repositoryを定義する."""

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        """指定roleを持つユーザーIDを取得する.

        Args:
            role_id (int): 検索対象のrole ID.

        Returns:
            list[int]: roleが割り当てられたユーザーID.
        """
        ...


logger: structlog.stdlib.BoundLogger = cast(
    "structlog.stdlib.BoundLogger",
    structlog.get_logger(__name__),
)


class SessionAuthorizationService:
    """ユーザー単位とrole単位のsession authorization更新をオーケストレーションする.

    Attributes:
        _permission_service (_PermissionAuthorizationComputer): authorization計算service.
        _session_store (SessionAuthorizationRuntime): session authorization更新store.
        _role_repository (_RoleUserLookup): roleに属するユーザーIDを取得するrepository.
    """

    _permission_service: _PermissionAuthorizationComputer
    _session_store: SessionAuthorizationRuntime
    _role_repository: _RoleUserLookup

    def __init__(
        self,
        *,
        permission_service: _PermissionAuthorizationComputer,
        session_store: SessionAuthorizationRuntime,
        role_repository: _RoleUserLookup,
    ) -> None:
        """Session authorization更新に必要な依存を初期化する.

        Args:
            permission_service (_PermissionAuthorizationComputer): authorization計算service.
            session_store (SessionAuthorizationRuntime): session authorization更新store.
            role_repository (_RoleUserLookup): roleに属するユーザーIDを取得するrepository.

        """
        self._permission_service = permission_service
        self._session_store = session_store
        self._role_repository = role_repository

    async def refresh_user_authorization(
        self,
        user_id: int,
    ) -> UserAuthorizationRefreshResult:
        """ユーザーの現在のroleからsession authorizationを計算して適用する.

        Args:
            user_id (int): authorizationを再計算するユーザーID.

        Returns:
            UserAuthorizationRefreshResult: 更新、active session不在、または計算失敗を表す結果.

        Notes:
            authorization計算の例外はFAILED結果へ変換する. active sessionがない場合は
            NO_ACTIVE_SESSIONを返す.
        """
        try:
            snapshot = await self._permission_service.compute_session_authorization(
                user_id,
            )
        except Exception:
            logger.exception(
                "authorization_refresh_compute_failed",
                user_id=user_id,
            )
            return UserAuthorizationRefreshResult(
                user_id=user_id,
                status=AuthorizationRefreshStatus.FAILED,
            )

        updated = await self._session_store.update_authorization(
            user_id=user_id,
            authorization=snapshot,
        )

        if not updated:
            logger.info(
                "authorization_refresh_no_active_session",
                user_id=user_id,
            )
            return UserAuthorizationRefreshResult(
                user_id=user_id,
                status=AuthorizationRefreshStatus.NO_ACTIVE_SESSION,
            )

        logger.info(
            "authorization_refreshed",
            user_id=user_id,
            privileges=int(snapshot.privileges),
            role_ids=list(snapshot.role_ids),
        )
        return UserAuthorizationRefreshResult(
            user_id=user_id,
            status=AuthorizationRefreshStatus.REFRESHED,
            authorization=snapshot,
        )

    async def refresh_role_authorization(
        self,
        role_id: int,
    ) -> RoleAuthorizationRefreshResult:
        """指定roleに属する全ユーザーのsession authorizationを更新する.

        Args:
            role_id (int): authorizationを更新するユーザーを検索するrole ID.

        Returns:
            RoleAuthorizationRefreshResult: role所属ユーザーごとの更新結果を集約した結果.

        Notes:
            各ユーザーを順番に更新し、個別の計算失敗はUserAuthorizationRefreshResultへ保持する.
        """
        user_ids = await self._role_repository.get_user_ids_for_role(role_id)

        user_results: list[UserAuthorizationRefreshResult] = []
        for user_id in user_ids:
            result = await self.refresh_user_authorization(user_id)
            user_results.append(result)

        logger.info(
            "role_authorization_refreshed",
            role_id=role_id,
            user_count=len(user_results),
        )
        return RoleAuthorizationRefreshResult(
            role_id=role_id,
            user_results=tuple(user_results),
        )
