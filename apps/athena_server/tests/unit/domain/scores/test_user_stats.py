"""Current user stats policyの集計とinvariantを検証する."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.domain.scores.user_stats import (
    UserCurrentStats,
    UserPerformanceBest,
    UserStatsHitTotals,
    UserStatsPerformanceTotals,
    UserStatsPolicy,
    calculate_ranked_score_from_scores,
)


def test_weighted_pp_sorts_by_pp_and_uses_official_like_decay() -> None:
    """Performance bestをPP降順に並べ0.95減衰でweighted PPを集計することを検証する.

    Returns:
        None: weighted, bonus, total PPの期待値を検証して完了する.

    Raises:
        AssertionError: PP順位または減衰係数による集計が変わった場合.
    """
    policy = UserStatsPolicy()
    bests = (
        UserPerformanceBest(pp=Decimal("50"), accuracy=0.90),
        UserPerformanceBest(pp=Decimal("100"), accuracy=0.95),
        UserPerformanceBest(pp=Decimal("25"), accuracy=0.80),
    )

    totals = policy.calculate_performance_totals(bests)

    assert totals.weighted_pp == Decimal("100") + Decimal("50") * Decimal("0.95") + Decimal(
        "25"
    ) * (Decimal("0.95") ** 2)
    assert totals.bonus_pp == Decimal("0")
    assert totals.total_pp == totals.weighted_pp


def test_policy_exposes_design_level_weighted_methods() -> None:
    """policyがPPとaccuracyの設計水準のweighted集計methodを公開することを検証する.

    Returns:
        None: 二つのmethodの加重結果を検証して完了する.

    Raises:
        AssertionError: public weighted集計methodまたは減衰計算が変わった場合.
    """
    policy = UserStatsPolicy()
    bests = (
        UserPerformanceBest(pp=Decimal("100"), accuracy=1.0),
        UserPerformanceBest(pp=Decimal("50"), accuracy=0.5),
    )

    assert policy.calculate_weighted_pp(bests) == Decimal("100") + Decimal("50") * Decimal("0.95")
    assert policy.calculate_weighted_accuracy(bests) == float(
        (Decimal("1.0") + Decimal("0.5") * Decimal("0.95")) / (Decimal("1") + Decimal("0.95"))
    )


def test_weighted_pp_uses_at_most_top_200_performances() -> None:
    """Weighted PP集計がPP上位200件だけを対象にすることを検証する.

    Returns:
        None: 201件入力に対する上位200件の期待値を検証して完了する.

    Raises:
        AssertionError: 集計対象件数が200件を超えるか順位選択が変わった場合.
    """
    policy = UserStatsPolicy()
    bests = tuple(
        UserPerformanceBest(pp=Decimal(300 - index), accuracy=0.98) for index in range(201)
    )

    totals = policy.calculate_performance_totals(bests)

    expected = sum(Decimal(300 - index) * (Decimal("0.95") ** index) for index in range(200))
    assert totals.weighted_pp == expected


def test_weighted_accuracy_uses_same_top_200_weight_sequence() -> None:
    """Weighted accuracyがweighted PPと同じ0.95減衰列を使うことを検証する.

    Returns:
        None: 手計算した加重accuracyとの一致を検証して完了する.

    Raises:
        AssertionError: accuracyの重み列または正規化計算が変わった場合.
    """
    policy = UserStatsPolicy()
    bests = (
        UserPerformanceBest(pp=Decimal("300"), accuracy=1.0),
        UserPerformanceBest(pp=Decimal("200"), accuracy=0.5),
        UserPerformanceBest(pp=Decimal("100"), accuracy=0.25),
    )

    totals = policy.calculate_performance_totals(bests)

    weight_0 = Decimal("1")
    weight_1 = Decimal("0.95")
    weight_2 = Decimal("0.95") ** 2
    expected = float(
        (Decimal("1.0") * weight_0 + Decimal("0.5") * weight_1 + Decimal("0.25") * weight_2)
        / (weight_0 + weight_1 + weight_2)
    )
    assert totals.accuracy == expected


def test_empty_performances_return_zero_policy_totals() -> None:
    """Performance bestが空の場合に全policy totalをゼロで返すことを検証する.

    Returns:
        None: PP, bonus, total, accuracyのゼロ値を検証して完了する.

    Raises:
        AssertionError: 空入力で非ゼロまたは別のaggregateを返した場合.
    """
    policy = UserStatsPolicy()

    totals = policy.calculate_performance_totals(())

    assert totals == UserStatsPerformanceTotals(
        weighted_pp=Decimal("0"),
        bonus_pp=Decimal("0"),
        total_pp=Decimal("0"),
        accuracy=0.0,
    )


def test_ranked_score_uses_best_eligible_score_per_beatmap() -> None:
    """Ranked scoreがbeatmapごとの最高eligible scoreだけを合計することを検証する.

    Returns:
        None: 同beatmapの低score, failed, 対象外scoreを除いた合計を検証して完了する.

    Raises:
        AssertionError: beatmapごとの最高値選択またはeligibility除外が変わった場合.
    """
    scores = (
        _score(beatmap_id=1, score=100_000),
        _score(beatmap_id=1, score=300_000),
        _score(beatmap_id=2, score=200_000),
        _score(beatmap_id=3, score=900_000, passed=False),
        _score(beatmap_id=4, score=800_000, leaderboard_eligible=False),
    )

    assert calculate_ranked_score_from_scores(scores) == 500_000


@pytest.mark.parametrize(
    ("ruleset", "hit_totals", "expected"),
    [
        (
            Ruleset.OSU,
            UserStatsHitTotals(count_300=3, count_100=1, count_50=1, count_miss=1),
            (3 * 300 + 1 * 100 + 1 * 50) / (6 * 300),
        ),
        (
            Ruleset.TAIKO,
            UserStatsHitTotals(count_300=3, count_100=1, count_miss=1),
            (3 * 300 + 1 * 150) / (5 * 300),
        ),
        (
            Ruleset.CATCH,
            UserStatsHitTotals(count_300=3, count_100=1, count_50=1, count_katu=2, count_miss=1),
            (3 + 1 + 1) / 8,
        ),
        (
            Ruleset.MANIA,
            UserStatsHitTotals(
                count_geki=2,
                count_300=3,
                count_katu=1,
                count_100=1,
                count_50=1,
                count_miss=1,
            ),
            (2 * 300 + 3 * 300 + 1 * 200 + 1 * 100 + 1 * 50) / (9 * 300),
        ),
    ],
)
def test_hit_totals_accuracy_uses_ruleset_formula(
    ruleset: Ruleset,
    hit_totals: UserStatsHitTotals,
    expected: float,
) -> None:
    """rulesetごとのhit total accuracy formulaを適用することを検証する.

    Args:
        ruleset (Ruleset): accuracy formulaを選ぶruleset.
        hit_totals (UserStatsHitTotals): formulaへ渡す判定数.
        expected (float): hand-calculated accuracy ratio.

    Returns:
        None: ruleset固有formulaの結果が期待ratioと一致することを検証して完了する.

    Raises:
        AssertionError: ruleset固有のhit total formulaが変更された場合.
    """
    policy = UserStatsPolicy()

    assert (
        policy.calculate_accuracy_from_hit_totals(
            ruleset=ruleset,
            hit_totals=hit_totals,
        )
        == expected
    )


def test_hit_totals_accuracy_returns_zero_for_empty_totals() -> None:
    """判定数が空の場合にhit total accuracyをゼロで返すことを検証する.

    Returns:
        None: 分母ゼロのosu! inputが0.0を返すことを検証して完了する.

    Raises:
        AssertionError: 空判定数で非ゼロ値または例外を返した場合.
    """
    policy = UserStatsPolicy()

    assert (
        policy.calculate_accuracy_from_hit_totals(
            ruleset=Ruleset.OSU,
            hit_totals=UserStatsHitTotals(),
        )
        == 0.0
    )


def test_default_current_stats_are_stable_safe() -> None:
    """Empty current statsがStable表示に安全な明示的default値を持つことを検証する.

    Returns:
        None: ID, PP, accuracy, rank, counter, play timeのdefault値を検証して完了する.

    Raises:
        AssertionError: empty statsがStable表示に必要なdefault値を変えた場合.
    """
    stats = UserCurrentStats.empty(user_id=42)

    assert stats.user_id == 42
    assert stats.pp == Decimal("0")
    assert stats.accuracy == 0.0
    assert stats.global_rank is None
    assert stats.play_count == 0
    assert stats.ranked_score == 0
    assert stats.total_score == 0
    assert stats.play_time_seconds is None


def test_performance_best_rejects_negative_pp() -> None:
    """UserPerformanceBestが負のPPをValueErrorで拒否することを検証する.

    Returns:
        None: 負のPP入力が固定error messageで失敗することを検証して完了する.

    Raises:
        AssertionError: 負のPPを有効なperformance bestとして受理した場合.
    """
    with pytest.raises(ValueError, match=r"^pp must be non-negative$"):
        _ = UserPerformanceBest(pp=Decimal("-0.01"), accuracy=0.95)


def test_performance_best_rejects_out_of_range_accuracy() -> None:
    """UserPerformanceBestが1.0を超えるaccuracyをValueErrorで拒否することを検証する.

    Returns:
        None: 範囲外accuracy入力が固定error messageで失敗することを検証して完了する.

    Raises:
        AssertionError: 1.0を超えるaccuracyを有効値として受理した場合.
    """
    with pytest.raises(
        ValueError,
        match=r"^accuracy must be between 0\.0 and 1\.0$",
    ):
        _ = UserPerformanceBest(pp=Decimal("10"), accuracy=1.01)


def test_performance_best_rejects_nan_accuracy() -> None:
    """UserPerformanceBestがNaN accuracyを有限範囲外として拒否することを検証する.

    Returns:
        None: NaN入力が固定error messageでValueErrorになることを検証して完了する.

    Raises:
        AssertionError: NaN accuracyを有効なperformance bestとして受理した場合.
    """
    with pytest.raises(
        ValueError,
        match=r"^accuracy must be a finite value between 0\.0 and 1\.0$",
    ):
        _ = UserPerformanceBest(pp=Decimal("10"), accuracy=float("nan"))


def test_current_stats_reject_invalid_identity() -> None:
    """UserCurrentStatsが正でないuser IDをValueErrorで拒否することを検証する.

    Returns:
        None: user ID 0が固定error messageで失敗することを検証して完了する.

    Raises:
        AssertionError: 正でないuser IDをcurrent statsとして受理した場合.
    """
    with pytest.raises(ValueError, match=r"^user_id must be positive$"):
        _ = UserCurrentStats(user_id=0)


def test_current_stats_reject_negative_values() -> None:
    """UserCurrentStatsが負のplay timeをValueErrorで拒否することを検証する.

    Returns:
        None: 負のplay timeが固定error messageで失敗することを検証して完了する.

    Raises:
        AssertionError: 負のplay timeをcurrent statsとして受理した場合.
    """
    with pytest.raises(
        ValueError,
        match=r"^play_time_seconds must be non-negative$",
    ):
        _ = UserCurrentStats(user_id=1, play_time_seconds=-1)


def test_current_stats_reject_invalid_global_rank() -> None:
    """UserCurrentStatsが存在するglobal rankに正数を要求することを検証する.

    Returns:
        None: rank 0が固定error messageで失敗することを検証して完了する.

    Raises:
        AssertionError: 正でないglobal rankをcurrent statsとして受理した場合.
    """
    with pytest.raises(
        ValueError,
        match=r"^global_rank must be positive when present$",
    ):
        _ = UserCurrentStats(user_id=1, global_rank=0)


def _score(
    *,
    beatmap_id: int,
    score: int,
    passed: bool = True,
    leaderboard_eligible: bool = True,
) -> Score:
    """Ranked score policy検証用の固定Scoreを指定条件で作成する.

    Args:
        beatmap_id (int): scoreを関連付けるbeatmap ID.
        score (int): score値.
        passed (bool): scoreをpassedとして扱うか.
        leaderboard_eligible (bool): submit時点のleaderboard eligibility.

    Returns:
        Score: 指定条件以外を固定したranking対象score.
    """
    return Score(
        id=None,
        user_id=42,
        beatmap_id=beatmap_id,
        beatmap_checksum=f"checksum-{beatmap_id}",
        online_checksum=f"online-{beatmap_id}-{score}",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=300,
        n100=20,
        n50=5,
        geki=0,
        katu=0,
        miss=0,
        score=score,
        max_combo=500,
        accuracy=0.98,
        grade=Grade.A,
        passed=passed,
        perfect=False,
        client_version="b20240201",
        submitted_at=datetime(2026, 6, 30, 0, 0, 0, tzinfo=UTC),
        beatmap_status_at_submission=BeatmapRankStatus.RANKED,
        leaderboard_eligible_at_submission=leaderboard_eligible,
    )
