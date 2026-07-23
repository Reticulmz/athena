"""role由来のserver-side authorizationを計算するquery serviceを提供するmodule.

query repositoryから取得したrole集合をPrivilegesとSessionAuthorizationへ集約する.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.sessions import SessionAuthorization

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class PermissionService:
    """userの全roleから内部Privilegesとsession authorizationを計算する.

    Attributes:
        _role_repo (RoleQueryRepository): userに割り当てられたroleを読むquery repository.
    """

    _role_repo: RoleQueryRepository

    def __init__(self, role_repo: RoleQueryRepository) -> None:
        """Role query repositoryを設定する.

        Args:
            role_repo (RoleQueryRepository): userに割り当てられたroleを読むrepository.
        """
        self._role_repo = role_repo

    async def compute_permissions(self, user_id: int) -> Privileges:
        """指定userに割り当てられたroleのPrivilegesをOR結合して返す.

        Args:
            user_id (int): 権限を計算するuserの識別子.

        Returns:
            Privileges: role由来のserver-side権限. roleがない場合はPrivileges.NONE.
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
        """指定userのrole集合からsession authorization snapshotを計算して返す.

        Args:
            user_id (int): authorizationを計算するuserの識別子.

        Returns:
            SessionAuthorization: 同じrole集合から導出したPrivilegesとposition順のrole ID群.

        Notes:
            loginとrefreshはこのmethodを共通のauthorization計算元として利用する.
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
