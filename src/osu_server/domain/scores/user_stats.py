"""Current user stats の値 object と計算 policy。"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from math import isfinite
from typing import TYPE_CHECKING

from osu_server.domain.scores.score import Playstyle, Ruleset

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.scores.score import Score

_MAX_WEIGHTED_BESTS = 200
_PP_WEIGHT_DECAY = Decimal("0.95")
_ZERO_DECIMAL = Decimal("0")


@dataclass(frozen=True, slots=True)
class UserPerformanceBest:
    """UserStats の PP と accuracy 集計に使う best performance row。

    Args:
        pp: current Performance Calculation 由来の非負 PP。
        accuracy: accepted Score 由来の accuracy ratio。0.0 から 1.0 の範囲。

    Raises:
        ValueError: PP が負、または accuracy が 0.0 から 1.0 の範囲外の場合。

    制約:
        この値はすでに eligibility 判定済みの best performance だけを表す。
    """

    pp: Decimal
    accuracy: float

    def __post_init__(self) -> None:
        """集計入力として不正な範囲の値を拒否する。"""
        if self.pp < _ZERO_DECIMAL:
            msg = "pp must be non-negative"
            raise ValueError(msg)
        _validate_accuracy(self.accuracy)


@dataclass(frozen=True, slots=True)
class UserStatsPerformanceTotals:
    """UserStatsPolicy が計算した PP と accuracy の current totals。"""

    weighted_pp: Decimal
    bonus_pp: Decimal
    total_pp: Decimal
    accuracy: float

    def __post_init__(self) -> None:
        """policy 結果として不正な範囲の値を拒否する。"""
        if self.weighted_pp < _ZERO_DECIMAL:
            msg = "weighted_pp must be non-negative"
            raise ValueError(msg)
        if self.bonus_pp < _ZERO_DECIMAL:
            msg = "bonus_pp must be non-negative"
            raise ValueError(msg)
        if self.total_pp < _ZERO_DECIMAL:
            msg = "total_pp must be non-negative"
            raise ValueError(msg)
        _validate_accuracy(self.accuracy)


@dataclass(frozen=True, slots=True)
class UserStatsHitTotals:
    """UserStats projection に保存する hit result totals。"""

    count_300: int = 0
    count_100: int = 0
    count_50: int = 0
    count_geki: int = 0
    count_katu: int = 0
    count_miss: int = 0

    def __post_init__(self) -> None:
        """hit count total として不正な負数を拒否する。"""
        _validate_non_negative("count_300", self.count_300)
        _validate_non_negative("count_100", self.count_100)
        _validate_non_negative("count_50", self.count_50)
        _validate_non_negative("count_geki", self.count_geki)
        _validate_non_negative("count_katu", self.count_katu)
        _validate_non_negative("count_miss", self.count_miss)

    def total_for_ruleset(self, ruleset: Ruleset) -> int:
        """ruleset ごとの accuracy denominator に使う total hit count を返す。"""
        match ruleset:
            case Ruleset.OSU:
                return self.count_300 + self.count_100 + self.count_50 + self.count_miss
            case Ruleset.TAIKO:
                return self.count_300 + self.count_100 + self.count_miss
            case Ruleset.CATCH:
                return (
                    self.count_300
                    + self.count_100
                    + self.count_50
                    + self.count_katu
                    + self.count_miss
                )
            case Ruleset.MANIA:
                return (
                    self.count_300
                    + self.count_100
                    + self.count_50
                    + self.count_geki
                    + self.count_katu
                    + self.count_miss
                )


@dataclass(frozen=True, slots=True)
class UserStatsScope:
    """UserStats projection の user/mode scope。"""

    user_id: int
    ruleset: Ruleset
    playstyle: Playstyle

    def __post_init__(self) -> None:
        """projection scope として不正な user_id を拒否する。"""
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class UserCurrentStats:
    """Stable game 内表示に渡す transport-neutral current user stats。"""

    user_id: int
    pp: Decimal = _ZERO_DECIMAL
    accuracy: float = 0.0
    global_rank: int | None = None
    play_count: int = 0
    ranked_score: int = 0
    total_score: int = 0
    max_combo: int = 0
    play_time_seconds: int | None = None
    hit_totals: UserStatsHitTotals = field(default_factory=UserStatsHitTotals)

    def __post_init__(self) -> None:
        """current stats として不正な範囲の値を拒否する。"""
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)
        if self.pp < _ZERO_DECIMAL:
            msg = "pp must be non-negative"
            raise ValueError(msg)
        _validate_accuracy(self.accuracy)
        if self.global_rank is not None and self.global_rank <= 0:
            msg = "global_rank must be positive when present"
            raise ValueError(msg)
        _validate_non_negative("play_count", self.play_count)
        _validate_non_negative("ranked_score", self.ranked_score)
        _validate_non_negative("total_score", self.total_score)
        _validate_non_negative("max_combo", self.max_combo)
        if self.play_time_seconds is not None:
            _validate_non_negative("play_time_seconds", self.play_time_seconds)

    @classmethod
    def empty(cls, *, user_id: int) -> UserCurrentStats:
        """score history がない known user 向けの stable-safe default を返す。"""
        return cls(user_id=user_id)


@dataclass(frozen=True, slots=True)
class UserStatsProjection:
    """DB に永続化する再構築可能な current UserStats projection。"""

    scope: UserStatsScope
    pp: Decimal = _ZERO_DECIMAL
    accuracy: float = 0.0
    play_count: int = 0
    ranked_score: int = 0
    total_score: int = 0
    max_combo: int = 0
    play_time_seconds: int | None = None
    hit_totals: UserStatsHitTotals = field(default_factory=UserStatsHitTotals)

    def __post_init__(self) -> None:
        """projection row として不正な範囲の値を拒否する。"""
        if self.pp < _ZERO_DECIMAL:
            msg = "pp must be non-negative"
            raise ValueError(msg)
        _validate_accuracy(self.accuracy)
        _validate_non_negative("play_count", self.play_count)
        _validate_non_negative("ranked_score", self.ranked_score)
        _validate_non_negative("total_score", self.total_score)
        _validate_non_negative("max_combo", self.max_combo)
        if self.play_time_seconds is not None:
            _validate_non_negative("play_time_seconds", self.play_time_seconds)

    def to_current_stats(self, *, global_rank: int | None = None) -> UserCurrentStats:
        """transport-neutral current stats 表示値へ変換する。"""
        return UserCurrentStats(
            user_id=self.scope.user_id,
            pp=self.pp,
            accuracy=self.accuracy,
            global_rank=global_rank,
            play_count=self.play_count,
            ranked_score=self.ranked_score,
            total_score=self.total_score,
            max_combo=self.max_combo,
            play_time_seconds=self.play_time_seconds,
            hit_totals=self.hit_totals,
        )


class UserStatsPolicy:
    """Current UserStats の PP と accuracy を計算する domain policy。"""

    def calculate_performance_totals(
        self,
        bests: tuple[UserPerformanceBest, ...],
    ) -> UserStatsPerformanceTotals:
        """best performance set から weighted PP, bonus PP, accuracy を計算する。

        Args:
            bests: eligibility 判定済み best performances。順序は問わない。

        Returns:
            上位 200 件に `0.95 ** index` を適用した current totals。

        制約:
            bonus PP は互換 evidence が得られるまで明示的に 0 とする。
        """
        weighted_bests = _top_weighted_bests(bests)
        weighted_pp = self.calculate_weighted_pp(weighted_bests)
        bonus_pp = self.calculate_bonus_pp(weighted_bests)
        return UserStatsPerformanceTotals(
            weighted_pp=weighted_pp,
            bonus_pp=bonus_pp,
            total_pp=weighted_pp + bonus_pp,
            accuracy=self.calculate_weighted_accuracy(weighted_bests),
        )

    def calculate_weighted_pp(
        self,
        bests: tuple[UserPerformanceBest, ...],
    ) -> Decimal:
        """上位 200 件の best performance に `0.95 ** index` を適用する。"""
        return sum(
            (
                best.pp * _weight_for_index(index)
                for index, best in enumerate(_top_weighted_bests(bests))
            ),
            start=_ZERO_DECIMAL,
        )

    def calculate_weighted_accuracy(
        self,
        bests: tuple[UserPerformanceBest, ...],
    ) -> float:
        """上位 200 件の best performance と同じ weight sequence で accuracy を返す。"""
        return _calculate_weighted_accuracy(_top_weighted_bests(bests))

    def calculate_bonus_pp(
        self,
        _bests: tuple[UserPerformanceBest, ...],
    ) -> Decimal:
        """未確認の bonus PP formula を使わず、明示的な 0 policy を返す。"""
        return _ZERO_DECIMAL

    def calculate_accuracy_from_hit_totals(
        self,
        *,
        ruleset: Ruleset,
        hit_totals: UserStatsHitTotals,
    ) -> float:
        """ruleset 別 formula で hit count totals から account accuracy を返す。"""
        total_hits = hit_totals.total_for_ruleset(ruleset)
        if total_hits == 0:
            return 0.0

        match ruleset:
            case Ruleset.OSU:
                weighted = (
                    hit_totals.count_300 * 300
                    + hit_totals.count_100 * 100
                    + hit_totals.count_50 * 50
                ) / (total_hits * 300)
            case Ruleset.TAIKO:
                weighted = (hit_totals.count_300 * 300 + hit_totals.count_100 * 150) / (
                    total_hits * 300
                )
            case Ruleset.CATCH:
                weighted = (
                    hit_totals.count_300 + hit_totals.count_100 + hit_totals.count_50
                ) / total_hits
            case Ruleset.MANIA:
                weighted = (
                    hit_totals.count_geki * 300
                    + hit_totals.count_300 * 300
                    + hit_totals.count_katu * 200
                    + hit_totals.count_100 * 100
                    + hit_totals.count_50 * 50
                ) / (total_hits * 300)
        return max(0.0, min(1.0, weighted))


def calculate_ranked_score_from_scores(scores: Iterable[Score]) -> int:
    """ranked score として beatmap ごとの最高 score 合計を返す。

    Args:
        scores: current stats scope に絞り込み済みの score 群。

    Returns:
        passed かつ leaderboard eligible な各 beatmap の最高 score 合計。

    制約:
        ruleset/playstyle/mod scope の判定は呼び出し側で済ませる。
    """
    best_scores_by_beatmap_id: dict[int, int] = {}
    for score in scores:
        if not score.passed or not score.leaderboard_eligible_at_submission:
            continue
        best_scores_by_beatmap_id[score.beatmap_id] = max(
            score.score,
            best_scores_by_beatmap_id.get(score.beatmap_id, 0),
        )
    return sum(best_scores_by_beatmap_id.values())


def _top_weighted_bests(
    bests: tuple[UserPerformanceBest, ...],
) -> tuple[UserPerformanceBest, ...]:
    return tuple(sorted(bests, key=lambda best: best.pp, reverse=True)[:_MAX_WEIGHTED_BESTS])


def _weight_for_index(index: int) -> Decimal:
    return _PP_WEIGHT_DECAY**index


def _calculate_weighted_accuracy(bests: tuple[UserPerformanceBest, ...]) -> float:
    if len(bests) == 0:
        return 0.0

    numerator = sum(
        (
            Decimal(str(best.accuracy)) * _weight_for_index(index)
            for index, best in enumerate(bests)
        ),
        start=_ZERO_DECIMAL,
    )
    denominator = sum(
        (_weight_for_index(index) for index in range(len(bests))),
        start=_ZERO_DECIMAL,
    )
    return float(numerator / denominator)


def _validate_accuracy(accuracy: float) -> None:
    if not isfinite(accuracy):
        msg = "accuracy must be a finite value between 0.0 and 1.0"
        raise ValueError(msg)
    if accuracy < 0.0 or accuracy > 1.0:
        msg = "accuracy must be between 0.0 and 1.0"
        raise ValueError(msg)


def _validate_non_negative(name: str, value: int) -> None:
    if value < 0:
        msg = f"{name} must be non-negative"
        raise ValueError(msg)


__all__ = (
    "UserCurrentStats",
    "UserPerformanceBest",
    "UserStatsHitTotals",
    "UserStatsPerformanceTotals",
    "UserStatsPolicy",
    "UserStatsProjection",
    "UserStatsScope",
    "calculate_ranked_score_from_scores",
)
