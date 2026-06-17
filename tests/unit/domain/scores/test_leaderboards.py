"""Beatmap leaderboard domain policy tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from osu_server.domain.scores.leaderboards import (
    ALL_MODS_FILTER_KEY,
    NO_MOD_FILTER_KEY,
    LeaderboardModFilter,
    LeaderboardScope,
    ScoreRankKey,
    filter_from_mod_combination,
    projection_keys_for_score,
    score_beats_current,
)
from osu_server.domain.scores.mods import Mod, ModCombination
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


def test_leaderboard_scope_distinguishes_all_mods_from_no_mod_filter() -> None:
    all_mods_scope = LeaderboardScope(
        beatmap_id=1,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mod_filter_key=ALL_MODS_FILTER_KEY,
    )
    no_mod_scope = LeaderboardScope(
        beatmap_id=1,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mod_filter_key=NO_MOD_FILTER_KEY,
    )

    assert all_mods_scope != no_mod_scope


def test_no_mod_filter_includes_preference_only_mods_but_excludes_nightcore() -> None:
    assert projection_keys_for_score(ModCombination.none()) == (
        ALL_MODS_FILTER_KEY,
        NO_MOD_FILTER_KEY,
    )
    assert NO_MOD_FILTER_KEY in projection_keys_for_score(ModCombination(Mod.SUDDEN_DEATH))
    assert NO_MOD_FILTER_KEY in projection_keys_for_score(ModCombination(Mod.PERFECT))
    assert NO_MOD_FILTER_KEY in projection_keys_for_score(ModCombination(Mod.MIRROR))
    assert NO_MOD_FILTER_KEY not in projection_keys_for_score(ModCombination(Mod.NIGHTCORE))


def test_nightcore_and_double_time_share_filter_key_and_keep_source_mods() -> None:
    nightcore_mods = ModCombination(Mod.NIGHTCORE)
    double_time_filter = filter_from_mod_combination(ModCombination(Mod.DOUBLE_TIME))
    nightcore_filter = filter_from_mod_combination(nightcore_mods)

    assert (
        nightcore_filter
        == double_time_filter
        == LeaderboardModFilter(
            key=int(Mod.DOUBLE_TIME),
        )
    )
    assert projection_keys_for_score(nightcore_mods) == (
        ALL_MODS_FILTER_KEY,
        int(Mod.DOUBLE_TIME),
    )
    assert nightcore_mods.mods == Mod.NIGHTCORE


def test_perfect_and_sudden_death_share_filter_key_and_keep_source_mods() -> None:
    perfect_mods = ModCombination(Mod.PERFECT)
    sudden_death_filter = filter_from_mod_combination(ModCombination(Mod.SUDDEN_DEATH))
    perfect_filter = filter_from_mod_combination(perfect_mods)

    assert (
        perfect_filter
        == sudden_death_filter
        == LeaderboardModFilter(
            key=int(Mod.SUDDEN_DEATH),
        )
    )
    assert projection_keys_for_score(perfect_mods) == (
        ALL_MODS_FILTER_KEY,
        NO_MOD_FILTER_KEY,
        int(Mod.SUDDEN_DEATH),
    )
    assert perfect_mods.mods == Mod.PERFECT


def test_multiple_gameplay_mods_use_exact_canonical_selected_key() -> None:
    hidden_nightcore = ModCombination(Mod.HIDDEN | Mod.NIGHTCORE)
    hidden_double_time = ModCombination(Mod.HIDDEN | Mod.DOUBLE_TIME)
    expected_key = int(Mod.HIDDEN | Mod.DOUBLE_TIME)

    assert filter_from_mod_combination(hidden_nightcore) == LeaderboardModFilter(
        key=expected_key,
    )
    assert filter_from_mod_combination(hidden_double_time) == LeaderboardModFilter(
        key=expected_key,
    )
    assert projection_keys_for_score(hidden_nightcore) == (
        ALL_MODS_FILTER_KEY,
        expected_key,
    )


def test_mirror_selected_filter_is_unsupported_while_score_can_remain_no_mod() -> None:
    mirror_mods = ModCombination(Mod.MIRROR)

    assert filter_from_mod_combination(mirror_mods) == LeaderboardModFilter(
        key=None,
        unsupported=True,
    )
    assert projection_keys_for_score(mirror_mods) == (
        ALL_MODS_FILTER_KEY,
        NO_MOD_FILTER_KEY,
    )
    assert mirror_mods.mods == Mod.MIRROR
