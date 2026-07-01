"""Command-side beatmap performance best projection repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from osu_server.domain.scores.score import Playstyle, Ruleset


@dataclass(frozen=True, slots=True)
class BeatmapPerformanceBestScope:
    """1 user と 1 beatmap scope に対する performance best の自然キー。"""

    user_id: int
    beatmap_id: int
    ruleset: Ruleset
    playstyle: Playstyle

    def __post_init__(self) -> None:
        """scope の永続化キーとして不正な非正値を拒否する。"""
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapPerformanceBest:
    """PP 優先で選ばれた 1 user と 1 beatmap scope の projection row。"""

    id: int | None
    scope: BeatmapPerformanceBestScope
    score_id: int
    performance_calculation_id: int
    pp: Decimal
    accuracy: float
    score: int
    submitted_at: datetime

    def __post_init__(self) -> None:
        """projection row として永続化できない値を拒否する。"""
        _validate_projection_values(
            row_id=self.id,
            score_id=self.score_id,
            performance_calculation_id=self.performance_calculation_id,
            pp=self.pp,
            accuracy=self.accuracy,
            score=self.score,
        )


@dataclass(frozen=True, slots=True)
class UpsertBeatmapPerformanceBest:
    """候補が現在 row より上位のときだけ projection row を置き換える command。"""

    scope: BeatmapPerformanceBestScope
    score_id: int
    performance_calculation_id: int
    pp: Decimal
    accuracy: float
    score: int
    submitted_at: datetime

    def __post_init__(self) -> None:
        """upsert 候補として永続化できない値を拒否する。"""
        _validate_projection_values(
            row_id=None,
            score_id=self.score_id,
            performance_calculation_id=self.performance_calculation_id,
            pp=self.pp,
            accuracy=self.accuracy,
            score=self.score,
        )


@dataclass(frozen=True, slots=True)
class BeatmapPerformanceBestUserProjectionSlice:
    """1 user 分を rebuild するときに置き換える projection slice。"""

    user_id: int

    def __post_init__(self) -> None:
        """slice key として不正な非正 user_id を拒否する。"""
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapPerformanceBestBeatmapProjectionSlice:
    """1 つ以上の beatmap 分を rebuild するときに置き換える projection slice。"""

    beatmap_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        """slice key として不正な空値または非正 beatmap_id を拒否する。"""
        if len(self.beatmap_ids) == 0:
            msg = "beatmap_ids must not be empty"
            raise ValueError(msg)
        if any(beatmap_id <= 0 for beatmap_id in self.beatmap_ids):
            msg = "beatmap_ids must be positive"
            raise ValueError(msg)


type BeatmapPerformanceBestProjectionSlice = (
    BeatmapPerformanceBestUserProjectionSlice | BeatmapPerformanceBestBeatmapProjectionSlice
)


class BeatmapPerformanceBestCommandRepository(Protocol):
    """Performance best projection の mutation と consistency check の port。"""

    async def lock_scope(self, scope: BeatmapPerformanceBestScope) -> None:
        """同一 performance best scope の refresh を transaction 内で直列化する。"""
        ...

    async def get_best(
        self,
        scope: BeatmapPerformanceBestScope,
    ) -> BeatmapPerformanceBest | None:
        """指定 scope の現在の performance best row を返す。"""
        ...

    async def upsert_if_better(
        self,
        command: UpsertBeatmapPerformanceBest,
    ) -> BeatmapPerformanceBest:
        """候補が PP 優先順で現在 row より上位なら永続化して現在 row を返す。"""
        ...

    async def replace_projection_slice(
        self,
        slice_: BeatmapPerformanceBestProjectionSlice,
        rows: Iterable[UpsertBeatmapPerformanceBest],
    ) -> None:
        """rebuild 済み slice 内の projection rows を supplied rows で置き換える。"""
        ...

    async def replace_scope(
        self,
        scope: BeatmapPerformanceBestScope,
        row: UpsertBeatmapPerformanceBest | None,
    ) -> BeatmapPerformanceBest | None:
        """1 scope の projection row を supplied winner で置換し、winner がなければ削除する。"""
        ...

    async def list_user_bests(
        self,
        *,
        user_id: int,
        ruleset: Ruleset,
        playstyle: Playstyle,
    ) -> tuple[BeatmapPerformanceBest, ...]:
        """指定 user/mode の current performance best rows を返す。"""
        ...


def _validate_projection_values(
    *,
    row_id: int | None,
    score_id: int,
    performance_calculation_id: int,
    pp: Decimal,
    accuracy: float,
    score: int,
) -> None:
    if row_id is not None and row_id <= 0:
        msg = "id must be positive when present"
        raise ValueError(msg)
    if score_id <= 0:
        msg = "score_id must be positive"
        raise ValueError(msg)
    if performance_calculation_id <= 0:
        msg = "performance_calculation_id must be positive"
        raise ValueError(msg)
    if pp < Decimal("0"):
        msg = "pp must not be negative"
        raise ValueError(msg)
    if not 0 <= accuracy <= 1:
        msg = "accuracy must be between 0 and 1"
        raise ValueError(msg)
    if score < 0:
        msg = "score must not be negative"
        raise ValueError(msg)
