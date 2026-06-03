"""SessionAuthorizationService — セッション認可の更新オーケストレーション。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from osu_server.domain.session_authorization import (
    AuthorizationRefreshStatus,
    UserAuthorizationRefreshResult,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.session_store import SessionStore
    from osu_server.services.permission_service import PermissionService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class SessionAuthorizationService:
    """ユーザー単位・ロール単位の認可 refresh をオーケストレーションする。"""

    _permission_service: PermissionService
    _session_store: SessionStore

    def __init__(
        self,
        *,
        permission_service: PermissionService,
        session_store: SessionStore,
    ) -> None:
        self._permission_service = permission_service
        self._session_store = session_store

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
