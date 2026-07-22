"""Authorization と display workflow 用 role read-only repository contract を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.roles import Role


class RoleQueryRepository(Protocol):
    """Authorization と display workflow 用 role read-only access を定義する.

    Notes:
        この Protocol は role と assignment projection を読むだけである. Role の作成や assignment
        変更を行わず Command Unit of Work を開始または commit/rollback しない.
    """

    async def get_by_id(self, role_id: int) -> Role | None:
        """Identifier に対応する Role を返す.

        Args:
            role_id (int): 検索する Role ID.

        Returns:
            Role | None: 対応する Role. 見つからない場合は `None`.
        """
        ...

    async def get_by_name(self, name: str) -> Role | None:
        """Name に対応する Role を返す.

        Args:
            name (str): 検索する Role name.

        Returns:
            Role | None: 対応する Role. 見つからない場合は `None`.
        """
        ...

    async def get_roles_for_user(self, user_id: int) -> list[Role]:
        """User に assignment された Role を返す.

        Args:
            user_id (int): Assignment を検索する User ID.

        Returns:
            list[Role]: User に assignment された Role の一覧. 対象がない場合は空の list.
        """
        ...

    async def get_default_role(self) -> Role:
        """Default Role を返す.

        Returns:
            Role: System が default として扱う Role.

        Raises:
            LookupError: name が `Default` の Role が存在しない場合.
        """
        ...

    async def get_user_ids_for_role(self, role_id: int) -> list[int]:
        """Role に assignment された User ID を返す.

        Args:
            role_id (int): Assignment を検索する Role ID.

        Returns:
            list[int]: Role に assignment された User ID の一覧. 対象がない場合は空の list.
        """
        ...
