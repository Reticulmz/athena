"""PermissionService — RBAC 権限計算とクライアントフラグ変換。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.role import ClientPermissions, Privileges

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.role_repository import RoleRepository


class PermissionService:
    """ユーザーの全ロールから内部権限を計算し、osu! クライアント用フラグに変換する。"""

    _role_repo: RoleRepository

    def __init__(self, role_repo: RoleRepository) -> None:
        self._role_repo = role_repo

    async def compute_permissions(self, user_id: int) -> Privileges:
        """*user_id* に割り当てられた全ロールの permissions を OR 結合して返す。

        ロールが存在しない場合は ``Privileges.NONE`` を返す。
        """
        roles = await self._role_repo.get_roles_for_user(user_id)
        result = Privileges.NONE
        for role in roles:
            result |= role.permissions
        return result

    @staticmethod
    def to_client_flags(privileges: Privileges) -> ClientPermissions:
        """内部 Privileges → osu! クライアント用 ClientPermissions に変換。

        マッピング:
            - MODERATOR → ClientPermissions.MODERATOR (2)
            - SUPPORTER → ClientPermissions.SUPPORTER (4)
            - ADMIN     → ClientPermissions.PEPPY     (8)
            - DEVELOPER → ClientPermissions.DEVELOPER (16)

        ClientPermissions.NORMAL (1) は常に含まれる。
        """
        flags = ClientPermissions.NORMAL

        mapping: tuple[tuple[Privileges, ClientPermissions], ...] = (
            (Privileges.MODERATOR, ClientPermissions.MODERATOR),
            (Privileges.SUPPORTER, ClientPermissions.SUPPORTER),
            (Privileges.ADMIN, ClientPermissions.PEPPY),
            (Privileges.DEVELOPER, ClientPermissions.DEVELOPER),
        )

        for priv, client_flag in mapping:
            if priv in privileges:
                flags |= client_flag

        return flags
