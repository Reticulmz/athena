"""Current UserStats projection の command repository 契約."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.user_stats import UserStatsProjection, UserStatsScope


class CurrentUserStatsCommandRepository(Protocol):
    """Current UserStats projection の mutation と consistency check の port.

    Notes:
        Runtime 実装は command Unit of Work から取得する.各操作は同じ Unit of Work が
        所有する transaction に参加し,この repository 自身は commit または rollback を
        実行しない.
    """

    async def lock_scope(self, scope: UserStatsScope) -> None:
        """同一 scope の projection refresh を transaction 内で直列化する.

        Args:
            scope (UserStatsScope): 排他制御する projection の自然キー.

        Returns:
            None: Transaction 終了まで scope lock を保持したことを示す.
        """
        ...

    async def get(self, scope: UserStatsScope) -> UserStatsProjection | None:
        """指定 scope の current UserStats projection row を返す.

        Args:
            scope (UserStatsScope): 取得する projection の自然キー.

        Returns:
            UserStatsProjection | None: 現在の projection row.未登録時は None.
        """
        ...

    async def replace(self, projection: UserStatsProjection) -> UserStatsProjection:
        """指定 scope の current UserStats projection row を supplied row で置き換える.

        Args:
            projection (UserStatsProjection): scope を代表する置換後の row.

        Returns:
            UserStatsProjection: 永続化後の projection row.
        """
        ...


__all__ = ("CurrentUserStatsCommandRepository",)
