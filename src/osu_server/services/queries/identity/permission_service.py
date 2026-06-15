"""PermissionService -- server-side RBAC authorization calculation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.sessions import SessionAuthorization

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class PermissionService:
    """ユーザーの全ロールから内部権限を計算する。"""

    _role_repo: RoleQueryRepository

    def __init__(self, role_repo: RoleQueryRepository) -> None:
        self._role_repo = role_repo

    async def compute_permissions(self, user_id: int) -> Privileges:
        """*user_id* に割り当てられた全ロールの permissions を OR 結合して返す。

        ロールが存在しない場合は ``Privileges.NONE`` を返す。
        """
        roles = await self._role_repo.get_roles_for_user(user_id)
        result = Privileges.NONE
        for role in roles:
            result |= role.permissions
        logger.info("permissions_computed", user_id=user_id, privileges=result)
        return result

    async def compute_session_authorization(
        self,
        user_id: int,
    ) -> SessionAuthorization:
        """*user_id* の全ロールから認可 snapshot を計算して返す。

        ``compute_permissions()`` と同じロールリストから privileges の OR と
        role_ids を単一の ``SessionAuthorization`` として返す。
        login と refresh の両方がこのメソッドを共有の認可計算元として使う。
        """
        roles = await self._role_repo.get_roles_for_user(user_id)
        privileges = Privileges.NONE
        role_ids: list[int] = []
        for role in roles:
            privileges |= role.permissions
            role_ids.append(role.id)
        return SessionAuthorization(
            privileges=privileges,
            role_ids=tuple(role_ids),
        )
