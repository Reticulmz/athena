"""In-memory command 側 current UserStats projection repository を実装する module."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.user_stats import UserStatsProjection, UserStatsScope
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryCurrentUserStatsCommandRepository:
    """User と mode ごとの current UserStats projection を管理する.

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

        Returns:
            None: state への参照を保持したことを示す.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def lock_scope(self, scope: UserStatsScope) -> None:
        """指定 user stats scope の lock を取得せずに完了する.

        Args:
            scope (UserStatsScope): lock 対象として渡される user, ruleset, playstyle scope.

        Returns:
            None: no-op が完了したことを示す.

        Notes:
            in-memory state は transaction-local snapshot として利用される前提であり,
            この実装は cross-transaction 又は cross-thread の排他を実現しない.
        """
        _ = scope

    async def get(self, scope: UserStatsScope) -> UserStatsProjection | None:
        """指定 scope の current UserStats projection row を返す.

        Args:
            scope (UserStatsScope): 検索する user, ruleset, playstyle scope.

        Returns:
            UserStatsProjection | None: 保存済み projection. 未登録なら None.
        """
        return self._state.current_user_stats_by_scope.get(_scope_key(scope))

    async def replace(self, projection: UserStatsProjection) -> UserStatsProjection:
        """指定 scope の current UserStats projection row を置き換える.

        Args:
            projection (UserStatsProjection): state に保存する projection.

        Returns:
            UserStatsProjection: 保存した引数 projection.

        Notes:
            同一 scope の既存 projection は無条件で上書きする.
        """
        self._state.current_user_stats_by_scope[_scope_key(projection.scope)] = projection
        return projection


def _scope_key(scope: UserStatsScope) -> tuple[int, int, int]:
    """UserStats scope を state index 用の不変 key に変換する.

    Args:
        scope (UserStatsScope): key 化する user stats scope.

    Returns:
        tuple[int, int, int]: user ID, ruleset value, playstyle value の順の key.
    """
    return (scope.user_id, scope.ruleset.value, scope.playstyle.value)


__all__ = ("InMemoryCurrentUserStatsCommandRepository",)
