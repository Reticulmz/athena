"""Role と assignment mutation の command-side repository 契約."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.identity.roles import Role


@runtime_checkable
class RoleCommandRepository(Protocol):
    """Role と assignment の mutation と consistency-check port.

    Notes:
        Runtime 実装は command Unit of Work から取得する。各操作は同じ Unit of Work が
        所有する transaction に参加し、この repository 自身は commit または rollback を
        実行しない.
    """

    async def get_by_id(self, role_id: int) -> Role | None:
        """Internal role identifier から Role を返す.

        Args:
            role_id (int): 検索する internal Role ID.

        Returns:
            Role | None: 一致する Role。存在しない場合は None.
        """
        ...

    async def get_by_name(self, name: str) -> Role | None:
        """Command-side validation 用に name から Role を返す.

        Args:
            name (str): 検索する Role name.

        Returns:
            Role | None: 一致する Role。存在しない場合は None.
        """
        ...

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        """Authorization check 用に user へ assignment 済みの Role を返す.

        Args:
            user_id (int): Role assignment を取得する User ID.

        Returns:
            list[Role]: User に assignment 済みの Role 群.
        """
        ...

    async def assign_role(self, user_id: int, role_id: int) -> None:
        """Role を user へ idempotently に assignment する.

        Args:
            user_id (int): Assignment 先 User ID.
            role_id (int): Assignment する Role ID.

        Returns:
            None: Assignment が Unit of Work に反映されたことを示す.
        """
        ...

    async def set_roles_for_user(self, user_id: int, role_ids: tuple[int, ...]) -> None:
        """User の全 Role assignment を指定した Role ID 群で置換する.

        Args:
            user_id (int): Assignment を置換する User ID.
            role_ids (tuple[int, ...]): 置換後に assignment する Role ID 群.

        Returns:
            None: Assignment の置換が Unit of Work に反映されたことを示す.
        """
        ...

    async def get_default_role(self) -> Role:
        """Registration command に必要な default Role を返す.

        Returns:
            Role: Registration へ assignment する default Role.

        Raises:
            LookupError: name が `Default` の Role が存在しない場合に送出する.
        """
        ...

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        """Command-side propagation 用に Role へ assignment 済みの User ID を返す.

        Args:
            role_id (int): Assignment を取得する Role ID.

        Returns:
            list[int]: Role へ assignment 済みの User ID 群.
        """
        ...
