"""In-memory command 側 personal best repository を実装する module."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.domain.scores.personal_best import (
    PersonalBest,
    PersonalBestScope,
    score_beats_personal_best,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.commands.personal_bests import UpsertPersonalBest
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryPersonalBestCommandRepository:
    """User, beatmap, mode, category scope ごとの personal best を管理する.

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

    async def get_by_scope(self, scope: PersonalBestScope) -> PersonalBest | None:
        """Personal best scope に対応する保存済み row を返す.

        Args:
            scope (PersonalBestScope): user, beatmap, ruleset, playstyle, category の検索 scope.

        Returns:
            PersonalBest | None: index と主記録が存在する personal best. 未登録又は不整合時は None.
        """
        key = _scope_key(scope)
        personal_best_id = self._state.personal_best_id_by_scope.get(key)
        if personal_best_id is None:
            return None
        return self._state.personal_bests_by_id.get(personal_best_id)

    async def upsert_if_better(self, command: UpsertPersonalBest) -> PersonalBest:
        """Candidate が domain policy 上より良い場合だけ personal best を保存する.

        Args:
            command (UpsertPersonalBest): scope, score ID, ranking value を持つ candidate.

        Returns:
            PersonalBest: 新規作成行, 更新行, 又は domain policy 上の既存同等以上行.

        Notes:
            新規 scope には ID を採番する. 既存 scope は score_beats_personal_best の結果が
            True の場合だけ score ID と ranking value を置き換える.
        """
        current = await self.get_by_scope(command.scope)
        if current is None:
            created = PersonalBest(
                id=self._state.next_personal_best_id,
                scope=command.scope,
                score_id=command.score_id,
                ranking_value=command.ranking_value,
            )
            assert created.id is not None
            self._state.next_personal_best_id += 1
            self._state.personal_bests_by_id[created.id] = created
            self._state.personal_best_id_by_scope[_scope_key(command.scope)] = created.id
            return created

        if not score_beats_personal_best(command.ranking_value, current.ranking_value):
            return current

        updated = replace(
            current,
            score_id=command.score_id,
            ranking_value=command.ranking_value,
        )
        assert updated.id is not None
        self._state.personal_bests_by_id[updated.id] = updated
        return updated


def _scope_key(scope: PersonalBestScope) -> tuple[int, int, int, int, str]:
    """Personal best scope を state index 用の不変 key に変換する.

    Args:
        scope (PersonalBestScope): key 化する personal best scope.

    Returns:
        tuple[int, int, int, int, str]: user ID, beatmap ID, ruleset value, playstyle value,
        category value の順の key.
    """
    return (
        scope.user_id,
        scope.beatmap_id,
        scope.ruleset.value,
        scope.playstyle.value,
        scope.category.value,
    )
