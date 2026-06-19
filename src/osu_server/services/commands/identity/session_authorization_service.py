"""SessionAuthorizationService — セッション認可の更新オーケストレーション。"""

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
    async def compute_session_authorization(
        self,
        user_id: int,
    ) -> SessionAuthorization: ...


class _RoleUserLookup(Protocol):
    async def get_user_ids_for_role(self, role_id: int) -> list[int]: ...


logger: structlog.stdlib.BoundLogger = cast(
    "structlog.stdlib.BoundLogger",
    structlog.get_logger(__name__),
)


class SessionAuthorizationService:
    """ユーザー単位・ロール単位の認可 refresh をオーケストレーションする。"""

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
        self._permission_service = permission_service
        self._session_store = session_store
        self._role_repository = role_repository

    async def refresh_user_authorization(
        self,
        user_id: int,
    ) -> UserAuthorizationRefreshResult:
        """*user_id* の現在のロール状態から認可 snapshot を計算し、
        active session に適用する。

        Returns:
            UserAuthorizationRefreshResult:
                - REFRESHED: 認可が更新された (authorization あり)
                - NO_ACTIVE_SESSION: active session なし (authorization なし)
                - FAILED: snapshot 計算に失敗 (authorization なし)
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
        """*role_id* に割り当てられた全ユーザーの認可を refresh する。

        RoleRepository.get_user_ids_for_role() で取得した各ユーザーに対し
        refresh_user_authorization() を呼び、結果を集約する。
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
