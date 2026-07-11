"""Unit tests for score performance domain policy."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.performance import (
    FormulaProfile,
    FormulaProfilePolicy,
    PerformanceCalculation,
    PerformanceCalculationState,
    PerformanceEligibilityPolicy,
)
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score


def _make_score(
    *,
    passed: bool = True,
    status: BeatmapRankStatus | str | None = BeatmapRankStatus.RANKED,
    leaderboard_eligible_at_submission: bool = True,
    mods: ModCombination | None = None,
) -> Score:
    status_value = status.value if isinstance(status, BeatmapRankStatus) else status
    score_mods = mods if mods is not None else ModCombination.none()
    return Score(
        id=1,
        user_id=100,
        beatmap_id=200,
        beatmap_checksum="0123456789abcdef0123456789abcdef",
        online_checksum="abcdef0123456789abcdef0123456789",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=score_mods,
        n300=300,
        n100=50,
        n50=10,
        geki=0,
        katu=0,
        miss=5,
        score=500000,
        max_combo=350,
        accuracy=0.95,
        grade=Grade.A,
        passed=passed,
        perfect=False,
        client_version="b20250101",
        submitted_at=datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC),
        beatmap_status_at_submission=BeatmapRankStatus(status_value)
        if status_value is not None
        else None,
        leaderboard_eligible_at_submission=leaderboard_eligible_at_submission,
    )


def test_performance_calculation_state_groups() -> None:
    assert PerformanceCalculationState.pending_states() == frozenset(
        {
            PerformanceCalculationState.QUEUED,
            PerformanceCalculationState.FETCHING_FILE,
            PerformanceCalculationState.CALCULATING,
        }
    )
    assert PerformanceCalculationState.terminal_states() == frozenset(
        {
            PerformanceCalculationState.COMPLETED,
            PerformanceCalculationState.UNAVAILABLE,
        }
    )
    assert PerformanceCalculationState.SUPERSEDED.is_historical


def test_completed_calculation_requires_pp_stars_and_calculated_timestamp() -> None:
    calculated_at = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)

    calculation = PerformanceCalculation(
        id=1,
        score_id=10,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
        pp=Decimal("123.45"),
        star_rating=Decimal("5.67"),
        calculator_name="rosu-pp-py",
        calculator_version="4.0.2",
        formula_profile=FormulaProfile.VANILLA_RANKED,
        beatmap_file_attachment_id=20,
        beatmap_file_checksum_md5="0123456789abcdef0123456789abcdef",
        unavailable_reason=None,
        calculated_at=calculated_at,
    )

    assert calculation.pp == Decimal("123.45")
    assert calculation.star_rating == Decimal("5.67")
    assert calculation.calculated_at == calculated_at


@pytest.mark.parametrize(
    "state",
    [
        PerformanceCalculationState.QUEUED,
        PerformanceCalculationState.FETCHING_FILE,
        PerformanceCalculationState.CALCULATING,
    ],
)
def test_pending_calculation_must_not_have_pp_or_unavailable_reason(
    state: PerformanceCalculationState,
) -> None:
    with pytest.raises(ValueError, match="pending calculation cannot have pp"):
        _ = PerformanceCalculation(
            id=1,
            score_id=10,
            state=state,
            is_current=True,
            pp=Decimal("1"),
            star_rating=None,
            calculator_name="rosu-pp-py",
            calculator_version="4.0.2",
            formula_profile=FormulaProfile.VANILLA_RANKED,
            beatmap_file_attachment_id=None,
            beatmap_file_checksum_md5=None,
            unavailable_reason=None,
            calculated_at=None,
        )


def test_unavailable_calculation_requires_reason_without_pp() -> None:
    calculation = PerformanceCalculation(
        id=1,
        score_id=10,
        state=PerformanceCalculationState.UNAVAILABLE,
        is_current=True,
        pp=None,
        star_rating=None,
        calculator_name="rosu-pp-py",
        calculator_version="4.0.2",
        formula_profile=FormulaProfile.VANILLA_RANKED,
        beatmap_file_attachment_id=20,
        beatmap_file_checksum_md5="0123456789abcdef0123456789abcdef",
        unavailable_reason="calculator_input_invalid",
        calculated_at=datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC),
    )

    assert calculation.unavailable_reason == "calculator_input_invalid"


def test_superseded_calculation_cannot_be_current() -> None:
    with pytest.raises(ValueError, match="superseded calculation cannot be current"):
        _ = PerformanceCalculation(
            id=1,
            score_id=10,
            state=PerformanceCalculationState.SUPERSEDED,
            is_current=True,
            pp=Decimal("123.45"),
            star_rating=Decimal("5.67"),
            calculator_name="rosu-pp-py",
            calculator_version="4.0.2",
            formula_profile=FormulaProfile.VANILLA_RANKED,
            beatmap_file_attachment_id=20,
            beatmap_file_checksum_md5="0123456789abcdef0123456789abcdef",
            unavailable_reason=None,
            calculated_at=datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "status",
    [BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED],
)
def test_ranked_and_approved_passed_vanilla_scores_are_eligible(
    status: BeatmapRankStatus,
) -> None:
    decision = PerformanceEligibilityPolicy().evaluate(_make_score(status=status))

    assert decision.is_eligible
    assert decision.reason is None


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (BeatmapRankStatus.LOVED, "beatmap_status_out_of_scope"),
        (BeatmapRankStatus.QUALIFIED, "beatmap_status_out_of_scope"),
        (BeatmapRankStatus.PENDING, "beatmap_status_out_of_scope"),
        (BeatmapRankStatus.UNKNOWN, "beatmap_status_out_of_scope"),
    ],
)
def test_non_ranked_pp_statuses_are_out_of_scope(
    status: BeatmapRankStatus,
    reason: str,
) -> None:
    decision = PerformanceEligibilityPolicy().evaluate(_make_score(status=status))

    assert not decision.is_eligible
    assert decision.reason == reason


def test_failed_score_is_out_of_scope() -> None:
    decision = PerformanceEligibilityPolicy().evaluate(_make_score(passed=False))

    assert not decision.is_eligible
    assert decision.reason == "score_failed"


def test_submission_ineligible_score_is_out_of_scope() -> None:
    decision = PerformanceEligibilityPolicy().evaluate_best_candidate(
        _make_score(leaderboard_eligible_at_submission=False)
    )

    assert not decision.is_eligible
    assert decision.reason == "score_not_eligible"


@pytest.mark.parametrize(
    ("mods", "reason"),
    [
        (ModCombination(Mod.RELAX), "playstyle_out_of_scope"),
        (ModCombination(Mod.AUTOPILOT), "playstyle_out_of_scope"),
    ],
)
def test_relax_and_autopilot_scores_are_out_of_scope(
    mods: ModCombination,
    reason: str,
) -> None:
    decision = PerformanceEligibilityPolicy().evaluate(_make_score(mods=mods))

    assert not decision.is_eligible
    assert decision.reason == reason


def test_missing_beatmap_status_is_out_of_scope() -> None:
    decision = PerformanceEligibilityPolicy().evaluate(_make_score(status=None))

    assert not decision.is_eligible
    assert decision.reason == "beatmap_status_missing"


def test_formula_profile_policy_returns_one_profile_per_playstyle() -> None:
    policy = FormulaProfilePolicy()

    assert policy.active_profile_for(Playstyle.VANILLA) is FormulaProfile.VANILLA_RANKED


def test_future_loved_relax_and_autopilot_pp_scopes_remain_disabled() -> None:
    eligibility_policy = PerformanceEligibilityPolicy()
    profile_policy = FormulaProfilePolicy()

    assert profile_policy.profiles_by_playstyle == {
        Playstyle.VANILLA: FormulaProfile.VANILLA_RANKED
    }
    assert not eligibility_policy.evaluate(_make_score(status=BeatmapRankStatus.LOVED)).is_eligible
    assert not eligibility_policy.evaluate(_make_score(mods=ModCombination(Mod.RELAX))).is_eligible
    assert not eligibility_policy.evaluate(
        _make_score(mods=ModCombination(Mod.AUTOPILOT))
    ).is_eligible


def test_formula_profile_policy_rejects_unknown_playstyle_object() -> None:
    policy = FormulaProfilePolicy()

    with pytest.raises(ValueError, match="unsupported playstyle"):
        _ = policy.active_profile_for(object())
