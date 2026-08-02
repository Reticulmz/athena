"""Committed in-memory state から Role を読む query adapter を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.identity.roles import Role
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryRoleQueryRepository:
    """Committed in-memory state を読む read-only Role repository.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): query ごとの committed snapshot を生成する factory.

    Notes:
        各 query は snapshot だけを読み, Role と assignment state を変更しない.
    """

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Committed snapshot を取得する factory を保持する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): read に使用する committed state factory.
        """
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def get_by_id(self, role_id: int) -> Role | None:
        """ID で Role を取得する.

        Args:
            role_id (int): 取得する Role の ID.

        Returns:
            Role | None: snapshot 内の Role. ID がなければ None.
        """
        state = self._factory.snapshot()
        return state.roles_by_id.get(role_id)

    async def get_by_name(self, name: str) -> Role | None:
        """完全一致する name の Role を取得する.

        Args:
            name (str): role_id_by_name 索引で検索する Role name.

        Returns:
            Role | None: 索引先の Role. name または Role がなければ None.

        Notes:
            name の正規化や大文字小文字の変換は行わない.
        """
        state = self._factory.snapshot()
        role_id = state.role_id_by_name.get(name)
        if role_id is None:
            return None
        return state.roles_by_id.get(role_id)

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        """User に割り当てられた Role を position 昇順で取得する.

        Args:
            user_id (int): Role assignment を読む User の ID.

        Returns:
            list[Role]: 存在する Role だけを position の昇順で並べた list. 割り当てがなければ空の
            list.
        """
        state = self._factory.snapshot()
        role_ids = state.role_ids_by_user_id.get(user_id, set())
        roles = [
            state.roles_by_id[role_id] for role_id in role_ids if role_id in state.roles_by_id
        ]
        return sorted(roles, key=lambda role: role.position)

    async def get_default_role(self) -> Role:
        """Name が Default の Role を取得する.

        Returns:
            Role: name 索引に存在する Default Role.

        Raises:
            LookupError: name が Default の Role が存在しない場合.
        """
        role = await self.get_by_name("Default")
        if role is None:
            msg = "No role named 'Default' exists"
            raise LookupError(msg)
        return role

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        """Role を割り当てられた User IDs を昇順で取得する.

        Args:
            role_id (int): assignment を検索する Role の ID.

        Returns:
            list[int]: role_id を含む assignment の User IDs を昇順にした list. 割り当てがなければ
            空の list.
        """
        state = self._factory.snapshot()
        user_ids = [
            user_id
            for user_id, role_ids in state.role_ids_by_user_id.items()
            if role_id in role_ids
        ]
        return sorted(user_ids)
