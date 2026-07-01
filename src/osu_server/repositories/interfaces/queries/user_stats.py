"""Current UserStats read-model repository contracts。"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from math import isfinite
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import UserStatsHitTotals

if TYPE_CHECKING:
    from osu_server.domain.scores.user_stats import UserPerformanceBest


@dataclass(frozen=True, slots=True)
class UserStatsSourceRow:
    """1 user 分の current stats source data。"""

    user_id: int
    play_count: int
    ranked_score: int
    total_score: int
    play_time_seconds: int | None
    best_performances: tuple[UserPerformanceBest, ...]
    max_combo: int = 0
    ruleset: Ruleset = Ruleset.OSU
    playstyle: Playstyle = Playstyle.VANILLA
    hit_totals: UserStatsHitTotals = field(default_factory=UserStatsHitTotals)
    pp: Decimal | None = None
    accuracy: float | None = None
    global_rank: int | None = None

    def __post_init__(self) -> None:
        """read-model として不正な範囲の値を拒否する。"""
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)
        _validate_non_negative("play_count", self.play_count)
        _validate_non_negative("ranked_score", self.ranked_score)
        _validate_non_negative("total_score", self.total_score)
        _validate_non_negative("max_combo", self.max_combo)
        if self.play_time_seconds is not None:
            _validate_non_negative("play_time_seconds", self.play_time_seconds)
        if self.pp is not None and self.pp < Decimal("0"):
            msg = "pp must be non-negative"
            raise ValueError(msg)
        if self.accuracy is not None:
            _validate_accuracy(self.accuracy)
        if self.global_rank is not None and self.global_rank <= 0:
            msg = "global_rank must be positive when present"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class UserStatsRankInput:
    """global rank 計算に使う leaderboard-visible user の best performances。"""

    user_id: int
    best_performances: tuple[UserPerformanceBest, ...] = ()
    pp: Decimal | None = None

    def __post_init__(self) -> None:
        """rank input として不正な user_id を拒否する。"""
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)
        if self.pp is not None and self.pp < Decimal("0"):
            msg = "pp must be non-negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class UserStatsSourceRead:
    """batch current stats read の source data 一式。"""

    users: tuple[UserStatsSourceRow, ...]
    rank_inputs: tuple[UserStatsRankInput, ...]


class UserStatsQueryRepository(Protocol):
    """Read-only current UserStats source data access。"""

    async def read_current_stats_sources(
        self,
        user_ids: tuple[int, ...],
        *,
        ruleset: Ruleset = Ruleset.OSU,
        playstyle: Playstyle = Playstyle.VANILLA,
    ) -> UserStatsSourceRead:
        """requested users の mode-scoped source data と rank inputs を返す。"""
        ...


def _validate_non_negative(name: str, value: int) -> None:
    if value < 0:
        msg = f"{name} must be non-negative"
        raise ValueError(msg)


def _validate_accuracy(accuracy: float) -> None:
    if not isfinite(accuracy):
        msg = "accuracy must be finite"
        raise ValueError(msg)
    if accuracy < 0.0 or accuracy > 1.0:
        msg = "accuracy must be between 0.0 and 1.0"
        raise ValueError(msg)


__all__ = (
    "UserStatsQueryRepository",
    "UserStatsRankInput",
    "UserStatsSourceRead",
    "UserStatsSourceRow",
)
