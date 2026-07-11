"""In-memory command-side beatmap leaderboard projection repository."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.domain.scores.leaderboards import score_beats_current
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBest,
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserProjectionSlice,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
        BeatmapLeaderboardProjectionSlice,
        UpsertBeatmapLeaderboardUserBest,
    )
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryBeatmapLeaderboardCommandRepository:
    """active な in-memory UoW state で Global all-mods best を管理する repository."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    async def get_user_best(
        self,
        scope: BeatmapLeaderboardUserBestScope,
    ) -> BeatmapLeaderboardUserBest | None:
        """指定 scope のユーザー最高 score を返す.

        Args:
            scope (BeatmapLeaderboardUserBestScope): 検索する Global all-mods scope.

        Returns:
            BeatmapLeaderboardUserBest | None: 保存行. 未登録時は None.
        """
        row_id = self._state.beatmap_leaderboard_user_best_id_by_scope.get(_scope_key(scope))
        if row_id is None:
            return None
        row = self._state.beatmap_leaderboard_user_bests_by_id.get(row_id)
        if row is None or row.scope.beatmap_checksum != scope.beatmap_checksum:
            return None
        return row

    async def upsert_if_better(
        self,
        command: UpsertBeatmapLeaderboardUserBest,
    ) -> BeatmapLeaderboardUserBest:
        """候補が現在値より上位の場合だけ state を更新する.

        Args:
            command (UpsertBeatmapLeaderboardUserBest): 比較対象の候補 score.

        Returns:
            BeatmapLeaderboardUserBest: 更新後の保存行.
        """
        current_id = self._state.beatmap_leaderboard_user_best_id_by_scope.get(
            _scope_key(command.scope)
        )
        current = (
            self._state.beatmap_leaderboard_user_bests_by_id.get(current_id)
            if current_id is not None
            else None
        )
        if current is None:
            created = BeatmapLeaderboardUserBest(
                id=self._state.next_beatmap_leaderboard_user_best_id,
                scope=command.scope,
                score_id=command.score_id,
                rank_key=command.rank_key,
            )
            assert created.id is not None
            self._state.next_beatmap_leaderboard_user_best_id += 1
            self._state.beatmap_leaderboard_user_bests_by_id[created.id] = created
            self._state.beatmap_leaderboard_user_best_id_by_scope[_scope_key(command.scope)] = (
                created.id
            )
            return created

        same_revision = current.scope.beatmap_checksum == command.scope.beatmap_checksum
        if same_revision and not score_beats_current(command.rank_key, current.rank_key):
            return current

        updated = replace(
            current,
            scope=command.scope,
            score_id=command.score_id,
            rank_key=command.rank_key,
        )
        assert updated.id is not None
        self._state.beatmap_leaderboard_user_bests_by_id[updated.id] = updated
        return updated

    async def replace_projection_slice(
        self,
        slice_: BeatmapLeaderboardProjectionSlice,
        rows: Iterable[UpsertBeatmapLeaderboardUserBest],
    ) -> None:
        """再構築対象 slice の Global best を置換する.

        Args:
            slice_ (BeatmapLeaderboardProjectionSlice): user または Beatmap の対象範囲.
            rows (Iterable[UpsertBeatmapLeaderboardUserBest]): 置換後の score 群.

        Returns:
            None: 置換が完了したことを示す.

        Raises:
            ValueError: 対象外 scope の行が含まれる場合.
        """
        rows_to_insert = tuple(rows)
        for row in rows_to_insert:
            if not _slice_contains(slice_, row.scope):
                msg = "replacement row is outside projection slice"
                raise ValueError(msg)

        for row_id in _row_ids_in_slice(self._state, slice_):
            row = self._state.beatmap_leaderboard_user_bests_by_id.pop(row_id)
            _ = self._state.beatmap_leaderboard_user_best_id_by_scope.pop(
                _scope_key(row.scope),
                None,
            )

        for row in rows_to_insert:
            _ = await self.upsert_if_better(row)


def _row_ids_in_slice(
    state: InMemoryCommandRepositoryState,
    slice_: BeatmapLeaderboardProjectionSlice,
) -> tuple[int, ...]:
    return tuple(
        row_id
        for row_id, row in state.beatmap_leaderboard_user_bests_by_id.items()
        if _slice_contains(slice_, row.scope)
    )


def _slice_contains(
    slice_: BeatmapLeaderboardProjectionSlice,
    scope: BeatmapLeaderboardUserBestScope,
) -> bool:
    if isinstance(slice_, BeatmapLeaderboardUserProjectionSlice):
        return scope.user_id == slice_.user_id
    return scope.beatmap_id in slice_.beatmap_ids


def _scope_key(scope: BeatmapLeaderboardUserBestScope) -> tuple[int, int, int, int]:
    return (
        scope.beatmap_id,
        scope.ruleset.value,
        scope.playstyle.value,
        scope.user_id,
    )
