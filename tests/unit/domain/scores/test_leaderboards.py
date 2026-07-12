"""Beatmap leaderboard domain policy tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from osu_server.domain.scores.leaderboards import (
    LeaderboardScope,
    ScoreRankKey,
    score_beats_current,
)
from osu_server.domain.scores.score import Playstyle, Ruleset

_BASE_TIME = datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC)


def _rank_key(*, score: int, seconds: int, score_id: int) -> ScoreRankKey:
    return ScoreRankKey(
        score=score,
        submitted_at=_BASE_TIME + timedelta(seconds=seconds),
        score_id=score_id,
    )


def test_rank_ordering_uses_score_then_submission_time_then_score_id() -> None:
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
    current = _rank_key(score=1000, seconds=10, score_id=20)
    candidate = _rank_key(score=1000, seconds=10, score_id=10)

    assert score_beats_current(candidate, current)
    assert not score_beats_current(current, candidate)
    assert score_beats_current(candidate, None)


def test_leaderboard_scope_has_no_mod_filter_dimension() -> None:
    scope = LeaderboardScope(
        beatmap_id=1,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
    )

    assert scope.beatmap_id == 1
