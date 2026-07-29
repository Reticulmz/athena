"""current user stats の値オブジェクトと計算 policy を定義する."""

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
    """current user stats の PP と accuracy 集計に使う best performance を表す.

    Attributes:
        pp (Decimal): current performance calculation 由来の非負 PP.
        accuracy (float): accepted score 由来の 0.0 から 1.0 の finite accuracy ratio.

    Notes:
        この値はすでに eligibility 判定済みの best performance だけを表す.
    """

    pp: Decimal
    accuracy: float

    def __post_init__(self) -> None:
        """集計入力となる PP と accuracy の範囲を検証する.

        Returns:
            None: pp と accuracy が集計可能であることを示す.

        Raises:
            ValueError: pp が負,accuracy が finite でない,または accuracy が範囲外の場合.
        """
        if self.pp < _ZERO_DECIMAL:
            msg = "pp must be non-negative"
            raise ValueError(msg)
        _validate_accuracy(self.accuracy)


@dataclass(frozen=True, slots=True)
class UserStatsPerformanceTotals:
    """UserStatsPolicy が計算した current PP と accuracy の合計を表す.

    Attributes:
        weighted_pp (Decimal): 上位 best performance の減衰重み付き PP 合計.
        bonus_pp (Decimal): formula policy が与える追加 PP.
        total_pp (Decimal): weighted_pp と bonus_pp の合計 PP.
        accuracy (float): 上位 best performance の減衰重み付き accuracy ratio.
    """

    weighted_pp: Decimal
    bonus_pp: Decimal
    total_pp: Decimal
    accuracy: float

    def __post_init__(self) -> None:
        """Policy 結果の PP と accuracy の範囲を検証する.

        Returns:
            None: PP 値が非負で accuracy が有効であることを示す.

        Raises:
            ValueError: PP 値が負,accuracy が finite でない,または accuracy が範囲外の場合.
        """
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
    """user stats projection に保存する hit result totals を表す.

    Attributes:
        count_300 (int): 300 判定の累積数.
        count_100 (int): 100 判定の累積数.
        count_50 (int): 50 判定の累積数.
        count_geki (int): geki 判定の累積数.
        count_katu (int): katu 判定の累積数.
        count_miss (int): miss 判定の累積数.
    """

    count_300: int = 0
    count_100: int = 0
    count_50: int = 0
    count_geki: int = 0
    count_katu: int = 0
    count_miss: int = 0

    def __post_init__(self) -> None:
        """すべての hit count total が非負であることを検証する.

        Returns:
            None: すべての累積 hit count が 0 以上であることを示す.

        Raises:
            ValueError: いずれかの累積 hit count が負の場合.
        """
        _validate_non_negative("count_300", self.count_300)
        _validate_non_negative("count_100", self.count_100)
        _validate_non_negative("count_50", self.count_50)
        _validate_non_negative("count_geki", self.count_geki)
        _validate_non_negative("count_katu", self.count_katu)
        _validate_non_negative("count_miss", self.count_miss)

    def total_for_ruleset(self, ruleset: Ruleset) -> int:
        """Ruleset ごとの accuracy denominator に使う総 hit 数を返す.

        Args:
            ruleset (Ruleset): hit count の集計式を選ぶ ruleset.

        Returns:
            int: ruleset の accuracy 式に含める判定数と miss 数の合計.

        Notes:
            OSU は geki/katu を,TAIKO は n50/geki/katu を,CATCH は geki を集計に含めない.
        """
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
    """user stats projection を一意にする user/ruleset/playstyle scope を表す.

    Attributes:
        user_id (int): projection を持つ user の正の ID.
        ruleset (Ruleset): 集計対象の ruleset.
        playstyle (Playstyle): 集計対象の playstyle.
    """

    user_id: int
    ruleset: Ruleset
    playstyle: Playstyle

    def __post_init__(self) -> None:
        """Projection scope の user ID が正であることを検証する.

        Returns:
            None: user_id が有効であることを示す.

        Raises:
            ValueError: user_id が 0 以下の場合.
        """
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class UserCurrentStats:
    """stable game 内表示へ渡す transport-neutral current user stats を表す.

    Attributes:
        user_id (int): stats を表示する user の正の ID.
        pp (Decimal): current PP. 未計算時は 0.
        accuracy (float): account accuracy ratio. 未計算時は 0.0.
        global_rank (int | None): global ranking の正の順位. 未取得時は None.
        play_count (int): accepted play の累積数.
        ranked_score (int): beatmap ごとの最高 eligible score を合計した ranked score.
        total_score (int): accepted score の累積値.
        max_combo (int): accepted score 中の最大 combo.
        play_time_seconds (int | None): 累積 play time の秒数. 未計測時は None.
        hit_totals (UserStatsHitTotals): account accuracy の基となる累積 hit count.
    """

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
        """Current stats の ID,rank,集計値の範囲を検証する.

        Returns:
            None: current stats が表示可能な範囲にあることを示す.

        Raises:
            ValueError: ID,PP,accuracy,rank,または集計値が許容範囲外の場合.
        """
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
        """Score history がない known user 用の stable-safe default を返す.

        Args:
            user_id (int): empty stats を作る user の ID.

        Returns:
            UserCurrentStats: PP とすべての集計値が 0,global_rank と play time が None の stats.

        Raises:
            ValueError: user_id が 0 以下の場合.
        """
        return cls(user_id=user_id)


@dataclass(frozen=True, slots=True)
class UserStatsProjection:
    """DB に永続化する再構築可能な current user stats projection を表す.

    Attributes:
        scope (UserStatsScope): projection を一意にする user/ruleset/playstyle scope.
        pp (Decimal): current PP. 未計算時は 0.
        accuracy (float): account accuracy ratio. 未計算時は 0.0.
        play_count (int): accepted play の累積数.
        ranked_score (int): beatmap ごとの最高 eligible score を合計した ranked score.
        total_score (int): accepted score の累積値.
        max_combo (int): accepted score 中の最大 combo.
        play_time_seconds (int | None): 累積 play time の秒数. 未計測時は None.
        hit_totals (UserStatsHitTotals): account accuracy の基となる累積 hit count.
    """

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
        """Projection row の PP,accuracy,集計値の範囲を検証する.

        Returns:
            None: projection 値が永続化可能な範囲にあることを示す.

        Raises:
            ValueError: PP,accuracy,または集計値が許容範囲外の場合.
        """
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
        """transport-neutral な current stats 表示値へ変換する.

        Args:
            global_rank (int | None): 表示時に付与する正の global ranking. 未取得時は None.

        Returns:
            UserCurrentStats: scope の user_id と projection の集計値を写した表示値.

        Raises:
            ValueError: global_rank が 0 以下の場合.
        """
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
    """current user stats の PP と accuracy を計算する domain policy を表す."""

    def calculate_performance_totals(
        self,
        bests: tuple[UserPerformanceBest, ...],
    ) -> UserStatsPerformanceTotals:
        """Best performance 集合から weighted PP,bonus PP,accuracy を計算する.

        Args:
            bests (tuple[UserPerformanceBest, ...]): eligibility 判定済みの best performance 群.
                順序は問わない.

        Returns:
            UserStatsPerformanceTotals: 上位 200 件に `0.95 ** index` を適用した current totals.

        Notes:
            bonus PP は互換 evidence が得られるまで明示的に 0 とする.
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
        """上位 200 件の best performance に減衰重みを適用した PP を返す.

        Args:
            bests (tuple[UserPerformanceBest, ...]): eligibility 判定済みの best performance 群.
                順序は問わない.

        Returns:
            Decimal: PP 降順の上位 200 件へ `0.95 ** index` を適用した合計.
        """
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
        """上位 200 件の減衰重みで weighted accuracy を返す.

        Args:
            bests (tuple[UserPerformanceBest, ...]): eligibility 判定済みの best performance 群.
                順序は問わない.

        Returns:
            float: PP と同じ順位と `0.95 ** index` を使う weighted accuracy. 入力が空なら 0.0.
        """
        return _calculate_weighted_accuracy(_top_weighted_bests(bests))

    def calculate_bonus_pp(
        self,
        _bests: tuple[UserPerformanceBest, ...],
    ) -> Decimal:
        """未確認の bonus PP formula を使わず,明示的な 0 を返す.

        Args:
            _bests (tuple[UserPerformanceBest, ...]): 将来の bonus formula 用 best performance 群.

        Returns:
            Decimal: 現在の policy では常に `Decimal("0")`.

        Notes:
            引数は将来の formula 拡張のため保持するが,現在は計算へ使用しない.
        """
        return _ZERO_DECIMAL

    def calculate_accuracy_from_hit_totals(
        self,
        *,
        ruleset: Ruleset,
        hit_totals: UserStatsHitTotals,
    ) -> float:
        """Ruleset 別 formula で hit count totals から account accuracy を返す.

        Args:
            ruleset (Ruleset): hit count の重み付け式を選ぶ ruleset.
            hit_totals (UserStatsHitTotals): 累積 hit count.

        Returns:
            float: 0.0 から 1.0 に収めた account accuracy. 対象 hit がない場合は 0.0.
        """
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
    """Ranked score として beatmap ごとの最高 eligible score 合計を返す.

    Args:
        scores (Iterable[Score]): current stats scope に絞り込み済みの score 群.

    Returns:
        int: passed かつ leaderboard eligible な各 beatmap の最高 score 合計.

    Notes:
        ruleset/playstyle/mod scope の判定は呼び出し側で済ませる.
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
    """PP 降順の上位 performance best 200 件を返す.

    Args:
        bests (tuple[UserPerformanceBest, ...]): 並び順を問わない best performance 群.

    Returns:
        tuple[UserPerformanceBest, ...]: PP 降順に並べた先頭 200 件以下の best performance.
    """
    return tuple(sorted(bests, key=lambda best: best.pp, reverse=True)[:_MAX_WEIGHTED_BESTS])


def _weight_for_index(index: int) -> Decimal:
    """PP 順位 index に対応する減衰重みを返す.

    Args:
        index (int): PP 降順の 0 始まり順位.

    Returns:
        Decimal: `0.95 ** index` で計算した重み.

    Notes:
        呼び出し側は非負の index を渡すことを前提とする. この関数は範囲検証を行わない.
    """
    return _PP_WEIGHT_DECAY**index


def _calculate_weighted_accuracy(bests: tuple[UserPerformanceBest, ...]) -> float:
    """既に順位付けされた best performance の weighted accuracy を計算する.

    Args:
        bests (tuple[UserPerformanceBest, ...]): PP 降順かつ最大 200 件に絞り込み済みの
            best performance 群.

    Returns:
        float: `0.95 ** index` の重み付き平均 accuracy. 入力が空なら 0.0.
    """
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
    """Accuracy が finite かつ 0.0 から 1.0 の範囲内か検証する.

    Args:
        accuracy (float): 検証する accuracy ratio.

    Returns:
        None: accuracy が集計に利用できる範囲にあることを示す.

    Raises:
        ValueError: accuracy が finite でない,または 0.0 から 1.0 の範囲外の場合.
    """
    if not isfinite(accuracy):
        msg = "accuracy must be a finite value between 0.0 and 1.0"
        raise ValueError(msg)
    if accuracy < 0.0 or accuracy > 1.0:
        msg = "accuracy must be between 0.0 and 1.0"
        raise ValueError(msg)


def _validate_non_negative(name: str, value: int) -> None:
    """整数集計値が非負か検証する.

    Args:
        name (str): error message に使う集計 field 名.
        value (int): 検証する整数集計値.

    Returns:
        None: value が 0 以上であることを示す.

    Raises:
        ValueError: value が負の場合.
    """
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
