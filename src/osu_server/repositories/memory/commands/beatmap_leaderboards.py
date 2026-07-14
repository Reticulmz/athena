"""In-memory command-side beatmap leaderboard projection repository."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.domain.scores.leaderboards import score_beats_current
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBest,
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserProjectionSlice,
    BeatmapLeaderboardUserScope,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
        BeatmapLeaderboardProjectionSlice,
        UpsertBeatmapLeaderboardUserBest,
    )
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryBeatmapLeaderboardCommandRepository:
    """active な in-memory UoW state で raw Mod scope best を管理する repository."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    async def lock_rebuild(self) -> None:
        """In-memory実装ではtransaction-local snapshotのためrebuild lockを持たない.

        Returns:
            None: no-opが完了したことを示す.
        """

    async def lock_scope(self, scope: BeatmapLeaderboardUserScope) -> None:
        """In-memory実装ではtransaction-local snapshotのためlockを持たない.

        Args:
            scope (BeatmapLeaderboardUserScope): Modを含まないserialization scope.

        Returns:
            None: no-opが完了したことを示す.
        """
        _ = scope

    async def get_user_best(
        self,
        scope: BeatmapLeaderboardUserBestScope,
    ) -> BeatmapLeaderboardUserBest | None:
        """指定 scope のユーザー最高 score を返す.

        Args:
            scope (BeatmapLeaderboardUserBestScope): 検索する raw Mod scope.

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

    async def get_global_user_best(
        self,
        scope: BeatmapLeaderboardUserScope,
    ) -> BeatmapLeaderboardUserBest | None:
        """全 raw Mod scope からユーザーの Global 最高 score を返す.

        Args:
            scope (BeatmapLeaderboardUserScope): Mod を含まない検索 scope.

        Returns:
            BeatmapLeaderboardUserBest | None: Global 最高 score. 未登録時は None.
        """
        candidates = (
            row
            for row in self._state.beatmap_leaderboard_user_bests_by_id.values()
            if _matches_global_scope(row.scope, scope)
        )
        return min(candidates, key=lambda row: row.rank_key.ordering_key, default=None)

    async def upsert_if_better(
        self,
        command: UpsertBeatmapLeaderboardUserBest,
    ) -> BeatmapLeaderboardUserBest:
        """候補が現在値より上位の場合だけ state を更新する.

        Args:
            command (UpsertBeatmapLeaderboardUserBest): 比較対象の候補 score.

        Returns:
            BeatmapLeaderboardUserBest: 更新後の保存行.

        Raises:
            ValueError: 同じ score_id が別 scope ですでに使用されている場合.
        """
        current_id = self._state.beatmap_leaderboard_user_best_id_by_scope.get(
            _scope_key(command.scope)
        )
        current = (
            self._state.beatmap_leaderboard_user_bests_by_id.get(current_id)
            if current_id is not None
            else None
        )
        _ensure_score_id_available(self._state, command.score_id, current_id=current_id)
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
        """再構築対象 slice の Mod別 best を置換する.

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


def _matches_global_scope(
    candidate: BeatmapLeaderboardUserBestScope,
    scope: BeatmapLeaderboardUserScope,
) -> bool:
    return (
        candidate.beatmap_id == scope.beatmap_id
        and candidate.beatmap_checksum == scope.beatmap_checksum
        and candidate.ruleset is scope.ruleset
        and candidate.playstyle is scope.playstyle
        and candidate.user_id == scope.user_id
    )


def _ensure_score_id_available(
    state: InMemoryCommandRepositoryState,
    score_id: int,
    *,
    current_id: int | None,
) -> None:
    duplicate = next(
        (
            row
            for row in state.beatmap_leaderboard_user_bests_by_id.values()
            if row.id != current_id and row.score_id == score_id
        ),
        None,
    )
    if duplicate is not None:
        msg = "score_id is already used by another leaderboard projection row"
        raise ValueError(msg)


def _scope_key(scope: BeatmapLeaderboardUserBestScope) -> tuple[int, int, int, int, int]:
    return (
        scope.beatmap_id,
        scope.ruleset.value,
        scope.playstyle.value,
        scope.user_id,
        scope.mods.to_persistence_bitmask(),
    )
