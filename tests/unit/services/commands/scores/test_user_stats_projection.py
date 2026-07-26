"""current UserStats projection command helperのUnit testを検証する."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.domain.scores.user_stats import UserStatsPolicy
from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
    BeatmapPerformanceBest,
    BeatmapPerformanceBestScope,
)
from osu_server.services.commands.scores.user_stats_projection import (
    build_current_user_stats_projection,
)

_NOW = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)


def test_projection_accuracy_uses_weighted_performance_best_rows() -> None:
    """Projection accuracyがperformance bestの加重値を使う契約を検証する.

    異なるaccuracyとPPを持つ二つのscoreおよびperformance bestを渡す条件で、policyの加重accuracy、
    hit totals、play count、total scoreがprojectionに観測できることを確認する.

    Returns:
        None: 加重accuracyとscore集計値を検証して、呼び出し側へ値を返さずに完了する.
    """
    projection = build_current_user_stats_projection(
        user_id=1000,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        scores=(
            _score(score_id=1, accuracy=0.50, n300=1, n100=1, score=100_000),
            _score(score_id=2, accuracy=0.40, n300=0, n100=1, score=200_000),
        ),
        bests=(
            _best(score_id=2, pp=Decimal("200"), accuracy=0.99),
            _best(score_id=1, pp=Decimal("100"), accuracy=0.80),
        ),
        policy=UserStatsPolicy(),
    )

    expected_accuracy = float(
        (Decimal("0.99") + Decimal("0.80") * Decimal("0.95")) / (Decimal("1") + Decimal("0.95"))
    )
    assert projection.accuracy == expected_accuracy
    assert projection.hit_totals.count_300 == 1
    assert projection.hit_totals.count_100 == 2
    assert projection.play_count == 2
    assert projection.total_score == 300_000


def _score(
    *,
    score_id: int,
    accuracy: float,
    n300: int,
    n100: int,
    score: int,
) -> Score:
    """Current UserStats projectionに渡すtest用scoreを作成する.

    Args:
        score_id (int): scoreとbeatmapのIDに使う値.
        accuracy (float): scoreに記録するaccuracy値.
        n300 (int): 300 hit数.
        n100 (int): 100 hit数.
        score (int): total score値.

    Returns:
        Score: current stats集計対象のtest用score.
    """
    return Score(
        id=score_id,
        user_id=1000,
        beatmap_id=score_id,
        beatmap_checksum=f"checksum-{score_id}",
        online_checksum=f"online-{score_id}",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=n300,
        n100=n100,
        n50=0,
        geki=0,
        katu=0,
        miss=0,
        score=score,
        max_combo=100,
        accuracy=accuracy,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="b20240201",
        submitted_at=_NOW,
        beatmap_status_at_submission=BeatmapRankStatus.RANKED,
        leaderboard_eligible_at_submission=True,
    )


def _best(*, score_id: int, pp: Decimal, accuracy: float) -> BeatmapPerformanceBest:
    """Current UserStats projectionに渡すtest用performance bestを作成する.

    Args:
        score_id (int): bestとscoreの関連付けに使うID.
        pp (Decimal): 加重PP集計に使うperformance値.
        accuracy (float): 加重accuracy集計に使う値.

    Returns:
        BeatmapPerformanceBest: 指定scoreに対応するtest用performance best row.
    """
    return BeatmapPerformanceBest(
        id=score_id,
        scope=BeatmapPerformanceBestScope(
            user_id=1000,
            beatmap_id=score_id,
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
        ),
        score_id=score_id,
        performance_calculation_id=score_id + 10_000,
        pp=pp,
        accuracy=accuracy,
        score=score_id * 100_000,
        submitted_at=_NOW,
    )
