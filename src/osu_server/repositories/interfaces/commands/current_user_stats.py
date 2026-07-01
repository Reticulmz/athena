"""Current UserStats projection command repository contracts。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.user_stats import UserStatsProjection, UserStatsScope


class CurrentUserStatsCommandRepository(Protocol):
    """current_user_stats projection の mutation と consistency check の port。"""

    async def lock_scope(self, scope: UserStatsScope) -> None:
        """同一 scope の projection refresh を transaction 内で直列化する。"""
        ...

    async def get(self, scope: UserStatsScope) -> UserStatsProjection | None:
        """指定 scope の current UserStats projection row を返す。"""
        ...

    async def replace(self, projection: UserStatsProjection) -> UserStatsProjection:
        """指定 scope の current UserStats projection row を supplied row で置き換える。"""
        ...


__all__ = ("CurrentUserStatsCommandRepository",)
