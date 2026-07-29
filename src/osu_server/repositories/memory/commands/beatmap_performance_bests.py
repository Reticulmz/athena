"""In-memory command 側 beatmap performance best projection repository を実装する module."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
    BeatmapPerformanceBest,
    BeatmapPerformanceBestScope,
    BeatmapPerformanceBestUserProjectionSlice,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.scores.score import Playstyle, Ruleset
    from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
        BeatmapPerformanceBestProjectionSlice,
        UpsertBeatmapPerformanceBest,
    )
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryBeatmapPerformanceBestCommandRepository:
    """Beatmap ごとの user performance best projection を管理する.

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

        Notes:
            state は clone せずに保持する. caller は state の排他所有を保証する必要がある.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def lock_scope(self, scope: BeatmapPerformanceBestScope) -> None:
        """指定 scope の lock を取得せずに完了する.

        Args:
            scope (BeatmapPerformanceBestScope): lock 対象として渡される performance best scope.

        Returns:
            None: no-op が完了したことを示す.

        Notes:
            in-memory state は transaction-local snapshot として利用される前提であり,
            この実装は cross-transaction 又は cross-thread の排他を実現しない.
        """
        _ = scope

    async def get_best(
        self,
        scope: BeatmapPerformanceBestScope,
    ) -> BeatmapPerformanceBest | None:
        """指定 scope の現在の performance best row を返す.

        Args:
            scope (BeatmapPerformanceBestScope): 検索する user, beatmap, ruleset, playstyle scope.

        Returns:
            BeatmapPerformanceBest | None: 保存行. index がないか主記録が欠けていれば None.
        """
        row_id = self._state.beatmap_performance_best_id_by_scope.get(_scope_key(scope))
        if row_id is None:
            return None
        return self._state.beatmap_performance_bests_by_id.get(row_id)

    async def upsert_if_better(
        self,
        command: UpsertBeatmapPerformanceBest,
    ) -> BeatmapPerformanceBest:
        """Candidate が現在 best より上位の場合だけ scope の行を保存する.

        Args:
            command (UpsertBeatmapPerformanceBest): candidate の scope と performance 値.

        Returns:
            BeatmapPerformanceBest: 新規作成行, 更新行, 又は既存の同等以上行.

        Notes:
            新規 scope には ID を採番する. 比較は pp の降順, submitted_at の昇順,
            score ID の昇順で行う. 更新時は既存 ID と scope index を保持する.
        """
        current = await self.get_best(command.scope)
        if current is None:
            created = BeatmapPerformanceBest(
                id=self._state.next_beatmap_performance_best_id,
                scope=command.scope,
                score_id=command.score_id,
                performance_calculation_id=command.performance_calculation_id,
                pp=command.pp,
                accuracy=command.accuracy,
                score=command.score,
                submitted_at=command.submitted_at,
            )
            assert created.id is not None
            self._state.next_beatmap_performance_best_id += 1
            self._state.beatmap_performance_bests_by_id[created.id] = created
            self._state.beatmap_performance_best_id_by_scope[_scope_key(command.scope)] = (
                created.id
            )
            return created

        if not _candidate_beats_current(command, current):
            return current

        updated = replace(
            current,
            score_id=command.score_id,
            performance_calculation_id=command.performance_calculation_id,
            pp=command.pp,
            accuracy=command.accuracy,
            score=command.score,
            submitted_at=command.submitted_at,
        )
        assert updated.id is not None
        self._state.beatmap_performance_bests_by_id[updated.id] = updated
        return updated

    async def replace_projection_slice(
        self,
        slice_: BeatmapPerformanceBestProjectionSlice,
        rows: Iterable[UpsertBeatmapPerformanceBest],
    ) -> None:
        """Projection slice 内の既存行を削除し supplied rows を再投入する.

        Args:
            slice_ (BeatmapPerformanceBestProjectionSlice): user 又は beatmap IDs の対象範囲.
            rows (Iterable[UpsertBeatmapPerformanceBest]): 置換後に upsert する performance rows.

        Returns:
            None: slice の削除と rows の投入が完了したことを示す.

        Raises:
            ValueError: rows に対象 slice 外の scope が含まれる場合.

        Notes:
            対象外 scope は既存行を削除する前に検証する. row は iterator から一度 tuple に
            materialize してから処理する.
        """
        rows_to_insert = tuple(rows)
        for row in rows_to_insert:
            if not _slice_contains(slice_, row.scope):
                msg = "replacement row is outside projection slice"
                raise ValueError(msg)

        for row_id in _row_ids_in_slice(self._state, slice_):
            row = self._state.beatmap_performance_bests_by_id.pop(row_id)
            _ = self._state.beatmap_performance_best_id_by_scope.pop(
                _scope_key(row.scope),
                None,
            )

        for row in rows_to_insert:
            _ = await self.upsert_if_better(row)

    async def replace_scope(
        self,
        scope: BeatmapPerformanceBestScope,
        row: UpsertBeatmapPerformanceBest | None,
    ) -> BeatmapPerformanceBest | None:
        """一つの scope の既存行を削除し optional winner を投入する.

        Args:
            scope (BeatmapPerformanceBestScope): 置換対象の一意 scope.
            row (UpsertBeatmapPerformanceBest | None): 新しい winner. None なら削除のみを行う.

        Returns:
            BeatmapPerformanceBest | None: 挿入した winner. row が None の場合は None.

        Raises:
            ValueError: row の scope が置換対象 scope と異なる場合.
        """
        if row is not None and row.scope != scope:
            msg = "replacement row is outside projection scope"
            raise ValueError(msg)

        existing_id = self._state.beatmap_performance_best_id_by_scope.pop(
            _scope_key(scope),
            None,
        )
        if existing_id is not None:
            _ = self._state.beatmap_performance_bests_by_id.pop(existing_id, None)
        if row is None:
            return None
        return await self.upsert_if_better(row)

    async def list_user_bests(
        self,
        *,
        user_id: int,
        ruleset: Ruleset,
        playstyle: Playstyle,
    ) -> tuple[BeatmapPerformanceBest, ...]:
        """指定 user と mode の current performance best rows を整列して返す.

        Args:
            user_id (int): 検索する user の識別子.
            ruleset (Ruleset): 検索する ruleset.
            playstyle (Playstyle): 検索する playstyle.

        Returns:
            tuple[BeatmapPerformanceBest, ...]: pp 降順, submitted_at 昇順, score ID 昇順の rows.
        """
        return tuple(
            sorted(
                (
                    row
                    for row in self._state.beatmap_performance_bests_by_id.values()
                    if row.scope.user_id == user_id
                    and row.scope.ruleset is ruleset
                    and row.scope.playstyle is playstyle
                ),
                key=lambda row: (-row.pp, row.submitted_at, row.score_id),
            )
        )


def _candidate_beats_current(
    command: UpsertBeatmapPerformanceBest,
    current: BeatmapPerformanceBest,
) -> bool:
    """Candidate が current performance best より優先されるか判定する.

    Args:
        command (UpsertBeatmapPerformanceBest): 比較する candidate.
        current (BeatmapPerformanceBest): 現在保存されている best row.

    Returns:
        bool: pp が高いか, 同 pp で submitted_at が早いか, さらに同時刻で score ID が
        小さい場合は True.
    """
    return (
        command.pp > current.pp
        or (command.pp == current.pp and command.submitted_at < current.submitted_at)
        or (
            command.pp == current.pp
            and command.submitted_at == current.submitted_at
            and command.score_id < current.score_id
        )
    )


def _row_ids_in_slice(
    state: InMemoryCommandRepositoryState,
    slice_: BeatmapPerformanceBestProjectionSlice,
) -> tuple[int, ...]:
    """Projection slice に含まれる repository row ID を列挙する.

    Args:
        state (InMemoryCommandRepositoryState): 検索対象の state snapshot.
        slice_ (BeatmapPerformanceBestProjectionSlice): user 又は beatmap IDs の対象範囲.

    Returns:
        tuple[int, ...]: slice に含まれる row ID の snapshot.
    """
    return tuple(
        row_id
        for row_id, row in state.beatmap_performance_bests_by_id.items()
        if _slice_contains(slice_, row.scope)
    )


def _slice_contains(
    slice_: BeatmapPerformanceBestProjectionSlice,
    scope: BeatmapPerformanceBestScope,
) -> bool:
    """Scope が performance best projection slice に含まれるか判定する.

    Args:
        slice_ (BeatmapPerformanceBestProjectionSlice): 判定する projection の対象範囲.
        scope (BeatmapPerformanceBestScope): membership を調べる performance best scope.

    Returns:
        bool: user slice では user ID が一致し, beatmap slice では beatmap ID が含まれる場合は
            True.
    """
    if isinstance(slice_, BeatmapPerformanceBestUserProjectionSlice):
        return scope.user_id == slice_.user_id
    return scope.beatmap_id in slice_.beatmap_ids


def _scope_key(scope: BeatmapPerformanceBestScope) -> tuple[int, int, int, int]:
    """Performance best scope を state index 用の不変 key に変換する.

    Args:
        scope (BeatmapPerformanceBestScope): key 化する performance best scope.

    Returns:
        tuple[int, int, int, int]: user ID, beatmap ID, ruleset value, playstyle value の順の key.
    """
    return (
        scope.user_id,
        scope.beatmap_id,
        scope.ruleset.value,
        scope.playstyle.value,
    )
