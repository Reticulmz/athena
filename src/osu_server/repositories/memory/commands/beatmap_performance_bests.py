"""In-memory command-side beatmap performance best projection repository."""

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
    """active in-memory UoW state を使う performance best command repository。"""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """transaction snapshot state を保持する。"""
        self._state: InMemoryCommandRepositoryState = state

    async def lock_scope(self, scope: BeatmapPerformanceBestScope) -> None:
        """In-memory 実装では transaction-local snapshot のため lock を持たない。"""
        _ = scope

    async def get_best(
        self,
        scope: BeatmapPerformanceBestScope,
    ) -> BeatmapPerformanceBest | None:
        """指定 scope の現在の performance best row を返す。"""
        row_id = self._state.beatmap_performance_best_id_by_scope.get(_scope_key(scope))
        if row_id is None:
            return None
        return self._state.beatmap_performance_bests_by_id.get(row_id)

    async def upsert_if_better(
        self,
        command: UpsertBeatmapPerformanceBest,
    ) -> BeatmapPerformanceBest:
        """候補が現在 row より上位なら保存し、永続化後の現在 row を返す。"""
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
        """指定 slice 内の stale rows を消して supplied rows を再投入する。"""
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
        """1 scope の stale row を削除し、supplied winner があれば投入する。"""
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
        """指定 user/mode の current performance best rows を返す。"""
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
    return tuple(
        row_id
        for row_id, row in state.beatmap_performance_bests_by_id.items()
        if _slice_contains(slice_, row.scope)
    )


def _slice_contains(
    slice_: BeatmapPerformanceBestProjectionSlice,
    scope: BeatmapPerformanceBestScope,
) -> bool:
    if isinstance(slice_, BeatmapPerformanceBestUserProjectionSlice):
        return scope.user_id == slice_.user_id
    return scope.beatmap_id in slice_.beatmap_ids


def _scope_key(scope: BeatmapPerformanceBestScope) -> tuple[int, int, int, int]:
    return (
        scope.user_id,
        scope.beatmap_id,
        scope.ruleset.value,
        scope.playstyle.value,
    )
