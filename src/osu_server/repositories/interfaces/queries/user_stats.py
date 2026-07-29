"""Current UserStats read model 用 read-only repository contract を定義する."""

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
    """一人分の current UserStats source data を表す.

    Attributes:
        user_id (int): Source data を所有する User ID. 正の値でなければならない.
        play_count (int): 対象 ruleset と playstyle の play count. 負の値は不可.
        ranked_score (int): 対象 scope の ranked score. 負の値は不可.
        total_score (int): 対象 scope の total score. 負の値は不可.
        play_time_seconds (int | None): 累積 play time 秒数. Unknown 時は `None`.
        best_performances (tuple[UserPerformanceBest, ...]): Rank 計算用 best performance.
        max_combo (int): 対象 scope の最大 combo. 負の値は不可.
        ruleset (Ruleset): Source row の ruleset.
        playstyle (Playstyle): Source row の playstyle.
        hit_totals (UserStatsHitTotals): 対象 scope の hit total.
        pp (Decimal | None): 現在の performance point. Unknown 時は `None`.
        accuracy (float | None): 0.0 から 1.0 の accuracy. Unknown 時は `None`.
        global_rank (int | None): Current global rank. Unknown 時は `None`.
    """

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
        """Read model として不正な値の範囲を拒否する.

        Returns:
            None: Source row が有効であることを表す.

        Raises:
            ValueError: User ID が正でない場合または count が負の場合.
            ValueError: PP が負の場合または accuracy が有限な 0.0 から 1.0 でない場合.
            ValueError: Global rank が指定されていて正でない場合.
        """
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
    """Global rank 計算に使う leaderboard visible User の performance を表す.

    Attributes:
        user_id (int): Rank input を所有する User ID. 正の値でなければならない.
        best_performances (tuple[UserPerformanceBest, ...]): Global rank 計算用 best performance.
        pp (Decimal | None): Current performance point. Unknown 時は `None`.
    """

    user_id: int
    best_performances: tuple[UserPerformanceBest, ...] = ()
    pp: Decimal | None = None

    def __post_init__(self) -> None:
        """Rank input として不正な User ID または PP を拒否する.

        Returns:
            None: Rank input が有効であることを表す.

        Raises:
            ValueError: User ID が正でない場合または PP が負の場合.
        """
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)
        if self.pp is not None and self.pp < Decimal("0"):
            msg = "pp must be non-negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class UserStatsSourceRead:
    """Batch current UserStats read の source data 一式を表す.

    Attributes:
        users (tuple[UserStatsSourceRow, ...]): 要求した User の current stats source row.
        rank_inputs (tuple[UserStatsRankInput, ...]): Global rank 計算用 input row.
    """

    users: tuple[UserStatsSourceRow, ...]
    rank_inputs: tuple[UserStatsRankInput, ...]


class UserStatsQueryRepository(Protocol):
    """Current UserStats source data への read-only access を定義する.

    Notes:
        この Protocol は current stats と rank input の source projection を返すだけである.
        UserStats projection を修復または更新せず Command Unit of Work を開始または
        commit/rollback しない.
    """

    async def read_current_stats_sources(
        self,
        user_ids: tuple[int, ...],
        *,
        ruleset: Ruleset = Ruleset.OSU,
        playstyle: Playstyle = Playstyle.VANILLA,
    ) -> UserStatsSourceRead:
        """Requested User の mode scoped source data と rank input を返す.

        Args:
            user_ids (tuple[int, ...]): Source data を要求する User ID.
            ruleset (Ruleset): 取得する ruleset. Default は `Ruleset.OSU`.
            playstyle (Playstyle): 取得する playstyle. Default は `Playstyle.VANILLA`.

        Returns:
            UserStatsSourceRead: Requested User の source row と global rank input.

        Notes:
            読み取り対象が欠けていてもこの query は durable state を作成または修復しない.
        """
        ...


def _validate_non_negative(name: str, value: int) -> None:
    """Integer value が非負であることを検証する.

    Args:
        name (str): Error message に使う value 名.
        value (int): 検証する integer value.

    Returns:
        None: Value が非負であることを表す.

    Raises:
        ValueError: Value が負の場合.
    """
    if value < 0:
        msg = f"{name} must be non-negative"
        raise ValueError(msg)


def _validate_accuracy(accuracy: float) -> None:
    """Accuracy が有限な 0.0 から 1.0 の範囲にあることを検証する.

    Args:
        accuracy (float): 検証する accuracy value.

    Returns:
        None: Accuracy が有効な範囲であることを表す.

    Raises:
        ValueError: Accuracy が有限でない場合または 0.0 から 1.0 の範囲外の場合.
    """
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
