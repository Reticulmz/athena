"""In-memory command-side current UserStats projection repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.user_stats import UserStatsProjection, UserStatsScope
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryCurrentUserStatsCommandRepository:
    """active in-memory UoW state を使う current UserStats command repository。"""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """transaction snapshot state を保持する。"""
        self._state: InMemoryCommandRepositoryState = state

    async def lock_scope(self, scope: UserStatsScope) -> None:
        """In-memory 実装では transaction-local snapshot のため lock を持たない。"""
        _ = scope

    async def get(self, scope: UserStatsScope) -> UserStatsProjection | None:
        """指定 scope の current UserStats projection row を返す。"""
        return self._state.current_user_stats_by_scope.get(_scope_key(scope))

    async def replace(self, projection: UserStatsProjection) -> UserStatsProjection:
        """指定 scope の current UserStats projection row を supplied row で置き換える。"""
        self._state.current_user_stats_by_scope[_scope_key(projection.scope)] = projection
        return projection


def _scope_key(scope: UserStatsScope) -> tuple[int, int, int]:
    return (scope.user_id, scope.ruleset.value, scope.playstyle.value)


__all__ = ("InMemoryCurrentUserStatsCommandRepository",)
