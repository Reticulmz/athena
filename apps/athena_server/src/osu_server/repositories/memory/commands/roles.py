"""In-memory command 側 role repository を実装する module."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.identity.roles import Role
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryRoleCommandRepository:
    """Role primary record, name index, user role assignment を command 用に管理する.

    Attributes:
        _state (InMemoryCommandRepositoryState): 所有 Unit of Work の可変 state snapshot.

    Notes:
        この repository は lock 又は thread synchronization を提供しない. 同じ state を
        複数 task 又は thread から同時に変更してはならない.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """Active Unit of Work の state snapshot を保持する.

        Args:
            state (InMemoryCommandRepositoryState): repository が直接読み書きする state.
        """
        self._state: InMemoryCommandRepositoryState = state

    def add_role(self, role: Role) -> None:
        """Command-side role check 用の role を state に seed する.

        Args:
            role (Role): 主記録と name index に保存する role.

        Returns:
            None: role 主記録と name index の更新が完了したことを示す.

        Notes:
            同じ ID 又は name の既存値を無条件で上書きする. 反対側の古い index は削除しない.
        """
        self._state.roles_by_id[role.id] = role
        self._state.role_id_by_name[role.name] = role.id

    async def get_by_id(self, role_id: int) -> Role | None:
        """Role ID から保存済み role を返す.

        Args:
            role_id (int): 検索する role の識別子.

        Returns:
            Role | None: 保存済み role. 未登録なら None.
        """
        return self._state.roles_by_id.get(role_id)

    async def get_by_name(self, name: str) -> Role | None:
        """Role name から保存済み role を返す.

        Args:
            name (str): 検索する完全一致 role name.

        Returns:
            Role | None: index と主記録が存在する role. 未登録又は不整合時は None.
        """
        role_id = self._state.role_id_by_name.get(name)
        if role_id is None:
            return None
        return self._state.roles_by_id.get(role_id)

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        """User に割り当てられた既存 role を position 昇順で返す.

        Args:
            user_id (int): role assignment を検索する user の識別子.

        Returns:
            list[Role]: role 主記録に現存する assignment の position 昇順 list.

        Notes:
            assignment にあるが role 主記録にない ID は結果から除外する.
        """
        role_ids = self._state.role_ids_by_user_id.get(user_id, set())
        roles = [
            self._state.roles_by_id[role_id]
            for role_id in role_ids
            if role_id in self._state.roles_by_id
        ]
        return sorted(roles, key=lambda role: role.position)

    async def assign_role(self, user_id: int, role_id: int) -> None:
        """User の role ID set に role ID を追加する.

        Args:
            user_id (int): role を割り当てる user の識別子.
            role_id (int): 追加する role の識別子.

        Returns:
            None: role ID を assignment set に追加したことを示す.

        Notes:
            user と role 主記録の存在は検証しない. set を使用するため同じ role ID の追加は
            idempotent.
        """
        self._state.role_ids_by_user_id.setdefault(user_id, set()).add(role_id)

    async def set_roles_for_user(self, user_id: int, role_ids: tuple[int, ...]) -> None:
        """User の role assignment を指定 role IDs に完全置換する.

        Args:
            user_id (int): assignment を置換する user の識別子.
            role_ids (tuple[int, ...]): 保存する role IDs. 空 tuple は assignment を削除する.

        Returns:
            None: assignment の置換又は削除が完了したことを示す.

        Notes:
            role 主記録の存在は検証しない. 重複した role IDs は set への変換で一つに集約される.
        """
        if role_ids:
            self._state.role_ids_by_user_id[user_id] = set(role_ids)
            return
        _ = self._state.role_ids_by_user_id.pop(user_id, None)

    async def get_default_role(self) -> Role:
        """Name が Default の role を返す.

        Returns:
            Role: name index と主記録に存在する Default role.

        Raises:
            LookupError: Default role が見つからない場合.
        """
        role = await self.get_by_name("Default")
        if role is None:
            msg = "No role named 'Default' exists"
            raise LookupError(msg)
        return role

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        """Role ID を assignment に含む user IDs を昇順で返す.

        Args:
            role_id (int): assignment を検索する role の識別子.

        Returns:
            list[int]: role ID を含む user IDs の昇順 list.

        Notes:
            role 主記録の存在は検証しない.
        """
        user_ids = [
            user_id
            for user_id, role_ids in self._state.role_ids_by_user_id.items()
            if role_id in role_ids
        ]
        return sorted(user_ids)
