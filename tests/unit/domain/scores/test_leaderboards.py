"""Beatmap leaderboard domain policyの順位とscope契約を検証する."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta

from osu_server.domain.scores.leaderboards import (
    LeaderboardScope,
    ScoreRankKey,
    score_beats_current,
)
from osu_server.domain.scores.score import Playstyle, Ruleset

_BASE_TIME = datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC)


def _rank_key(*, score: int, seconds: int, score_id: int) -> ScoreRankKey:
    """固定基準時刻から順位比較用のScoreRankKeyを作成する.

    Args:
        score (int): 比較対象のscore値.
        seconds (int): 基準時刻へ加算する送信秒数.
        score_id (int): 同順位時の最終比較に使うscore ID.

    Returns:
        ScoreRankKey: 指定した順位比較値を持つkey.
    """
    return ScoreRankKey(
        score=score,
        submitted_at=_BASE_TIME + timedelta(seconds=seconds),
        score_id=score_id,
    )


def test_rank_ordering_uses_score_then_submission_time_then_score_id() -> None:
    """順位がscore降順, 送信時刻昇順, score ID昇順で決まることを検証する.

    Returns:
        None: 混在した候補のsort結果を固定順序で検証して完了する.

    Raises:
        AssertionError: 任意の順位tie-break規則が変更された場合.
    """
    higher_score = _rank_key(score=2000, seconds=30, score_id=30)
    earlier_submission = _rank_key(score=1000, seconds=10, score_id=30)
    lower_score_id = _rank_key(score=1000, seconds=10, score_id=20)
    lower_score = _rank_key(score=999, seconds=0, score_id=1)

    ordered = sorted(
        [earlier_submission, lower_score, higher_score, lower_score_id],
        key=lambda rank_key: rank_key.ordering_key,
    )

    assert ordered == [higher_score, lower_score_id, earlier_submission, lower_score]


def test_score_beats_current_uses_lower_score_id_as_final_tie_break() -> None:
    """同scoreかつ同時刻では小さいscore IDを代表scoreとして採用することを検証する.

    Returns:
        None: tie-breakと未登録currentの候補採用を検証して完了する.

    Raises:
        AssertionError: score IDによる最終順位または空currentの扱いが変わった場合.
    """
    current = _rank_key(score=1000, seconds=10, score_id=20)
    candidate = _rank_key(score=1000, seconds=10, score_id=10)

    assert score_beats_current(candidate, current)
    assert not score_beats_current(current, candidate)
    assert score_beats_current(candidate, None)


def test_leaderboard_scope_has_no_mod_filter_dimension() -> None:
    """LeaderboardScopeがread filter用Mod fieldを持たないことを確認する.

    Returns:
        None: scope fieldがBeatmap, ruleset, playstyleだけであることを検証して完了する.

    Raises:
        AssertionError: Mod filter dimensionまたは想定外fieldが追加された場合.
    """
    scope = LeaderboardScope(
        beatmap_id=1,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
    )

    assert scope.beatmap_id == 1
    assert {field.name for field in fields(LeaderboardScope)} == {
        "beatmap_id",
        "ruleset",
        "playstyle",
    }
