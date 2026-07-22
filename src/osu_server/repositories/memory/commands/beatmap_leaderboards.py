"""In-memory command 側 beatmap leaderboard projection repository を実装する module."""

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
    """Raw mod scope ごとの beatmap leaderboard user best を管理する.

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

        Notes:
            state は clone せずに保持する. caller は state の排他所有を保証する必要がある.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def lock_rebuild(self) -> None:
        """Rebuild 全体の lock を取得せずに完了する.

        Returns:
            None: no-op が完了したことを示す.

        Notes:
            in-memory state は transaction-local snapshot として利用される前提であり,
            この実装は cross-transaction 又は cross-thread の排他を実現しない.
        """

    async def lock_scope(self, scope: BeatmapLeaderboardUserScope) -> None:
        """指定 scope の lock を取得せずに完了する.

        Args:
            scope (BeatmapLeaderboardUserScope): mod を含まない serialization scope.

        Returns:
            None: no-op が完了したことを示す.

        Notes:
            in-memory state は transaction-local snapshot として利用される前提であり,
            この実装は cross-transaction 又は cross-thread の排他を実現しない.
        """
        _ = scope

    async def get_user_best(
        self,
        scope: BeatmapLeaderboardUserBestScope,
    ) -> BeatmapLeaderboardUserBest | None:
        """指定 raw mod scope に保存した user best を返す.

        Args:
            scope (BeatmapLeaderboardUserBestScope): 検索する raw mod scope.

        Returns:
            BeatmapLeaderboardUserBest | None: 保存行. index がないか checksum が不一致なら None.
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
        """全 raw mod scope から user の global best を返す.

        Args:
            scope (BeatmapLeaderboardUserScope): mod を含まない検索 scope.

        Returns:
            BeatmapLeaderboardUserBest | None:
                最小 ordering key を持つ global best. 候補がなければ None.
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
        """Candidate を raw mod scope の best として必要な場合だけ保存する.

        Args:
            command (UpsertBeatmapLeaderboardUserBest): candidate の scope, score ID, rank key.

        Returns:
            BeatmapLeaderboardUserBest: 新規作成行, 更新行, 又は同 revision の既存上位行.

        Raises:
            ValueError: command.score_id が別 projection row にすでに使用されている場合.

        Notes:
            scope に行がなければ新規 ID を採番する. 同じ beatmap checksum の既存行より
            candidate が上位でなければ既存行を返す. checksum が異なる場合は rank key に
            かかわらず既存行を candidate で置換する.
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
        """Rebuild 対象 slice の raw mod best を supplied rows で置換する.

        Args:
            slice_ (BeatmapLeaderboardProjectionSlice): user 又は beatmap IDs の対象範囲.
            rows (Iterable[UpsertBeatmapLeaderboardUserBest]): 置換後に upsert する score 群.

        Returns:
            None: 既存 slice 行の削除と rows の投入が完了したことを示す.

        Raises:
            ValueError: rows に対象外 scope 又は他行と重複する score ID が含まれる場合.

        Notes:
            対象外 scope は既存行を削除する前に検証する. score ID の重複は個別 upsert 中に
            検出するため, この in-memory 実装は失敗時に repository 内 rollback を行わない.
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
    """Projection slice に含まれる repository row ID を列挙する.

    Args:
        state (InMemoryCommandRepositoryState): 検索対象の state snapshot.
        slice_ (BeatmapLeaderboardProjectionSlice): user 又は beatmap IDs の対象範囲.

    Returns:
        tuple[int, ...]: slice に含まれる row ID の snapshot.
    """
    return tuple(
        row_id
        for row_id, row in state.beatmap_leaderboard_user_bests_by_id.items()
        if _slice_contains(slice_, row.scope)
    )


def _slice_contains(
    slice_: BeatmapLeaderboardProjectionSlice,
    scope: BeatmapLeaderboardUserBestScope,
) -> bool:
    """Scope が projection slice の対象に含まれるか判定する.

    Args:
        slice_ (BeatmapLeaderboardProjectionSlice): 判定する projection の対象範囲.
        scope (BeatmapLeaderboardUserBestScope): membership を調べる raw mod scope.

    Returns:
        bool: user slice では user ID が一致し, beatmap slice では beatmap ID が含まれる場合は
            True.
    """
    if isinstance(slice_, BeatmapLeaderboardUserProjectionSlice):
        return scope.user_id == slice_.user_id
    return scope.beatmap_id in slice_.beatmap_ids


def _matches_global_scope(
    candidate: BeatmapLeaderboardUserBestScope,
    scope: BeatmapLeaderboardUserScope,
) -> bool:
    """Candidate scope が global best 検索 scope と完全に一致するか判定する.

    Args:
        candidate (BeatmapLeaderboardUserBestScope): raw mod を含む保存済み scope.
        scope (BeatmapLeaderboardUserScope): raw mod を含まない検索 scope.

    Returns:
        bool: beatmap ID, checksum, ruleset, playstyle, user ID がすべて一致する場合は True.
    """
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
    """Score ID が現在行以外の projection row に未使用であることを検証する.

    Args:
        state (InMemoryCommandRepositoryState): 検索対象の state snapshot.
        score_id (int): 使用可否を確認する score ID.
        current_id (int | None): 更新対象の既存 row ID. この row 自身は重複として扱わない.

    Returns:
        None: score ID が使用可能であることを示す.

    Raises:
        ValueError: score ID が別 projection row に使用されている場合.
    """
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
    """Raw mod leaderboard scope を state index 用の不変 key に変換する.

    Args:
        scope (BeatmapLeaderboardUserBestScope): key 化する user best scope.

    Returns:
        tuple[int, int, int, int, int]: beatmap ID, ruleset value, playstyle value, user ID,
        persistence mod bitmask の順の key.
    """
    return (
        scope.beatmap_id,
        scope.ruleset.value,
        scope.playstyle.value,
        scope.user_id,
        scope.mods.to_persistence_bitmask(),
    )
