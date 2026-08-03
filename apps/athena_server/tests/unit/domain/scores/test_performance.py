"""Score performance calculationのstateとeligibility policyを検証する."""

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
    """Performance policy評価用の有効なScoreを指定条件で作成する.

    Args:
        passed (bool): scoreをpassedとして扱うか.
        status (BeatmapRankStatus | str | None): submit時点のbeatmap statusまたは未設定値.
        leaderboard_eligible_at_submission (bool): submit時点でleaderboard対象か.
        mods (ModCombination | None): 使用するmod群. Noneならmodなしにする.

    Returns:
        Score: 指定条件以外を固定したperformance評価用score.

    Raises:
        ValueError: status文字列がBeatmapRankStatusとして無効な場合.
    """
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
    """Performance calculation lifecycleのstate分類を検証する.

    pending, terminal, historicalに属するstate集合を比較する.

    Returns:
        None: state集合とSUPERSEDEDのhistorical性を検証して完了する.

    Raises:
        AssertionError: lifecycle state分類が変更された場合.
    """
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
    """COMPLETED calculationがPP, star rating, calculated timestampを保持できることを検証する.

    Returns:
        None: 構築済みcalculationの完了payloadを検証して完了する.

    Raises:
        AssertionError: completed stateの必須payload保持が変わった場合.
    """
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
    """Pending calculationがPPまたはunavailable reasonを保持できないことを検証する.

    Args:
        state (PerformanceCalculationState): 検証するpending lifecycle state.

    Returns:
        None: 不正payloadの構築がValueErrorになることを検証して完了する.

    Raises:
        AssertionError: pending stateが完了payloadを受理した場合.
    """
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
    """UNAVAILABLE calculationがreasonを持ちPPを持たないstate payloadを受理することを検証する.

    Returns:
        None: unavailable reasonを保持するcalculationを検証して完了する.

    Raises:
        AssertionError: unavailable stateのreason payloadが失われた場合.
    """
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
    """SUPERSEDED calculationをcurrentとして生成できないことを検証する.

    Returns:
        None: 矛盾するstate payloadがValueErrorになることを検証して完了する.

    Raises:
        AssertionError: historical calculationをcurrentとして受理した場合.
    """
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
    """passedのRANKEDまたはAPPROVED vanilla scoreをPP対象にすることを検証する.

    Args:
        status (BeatmapRankStatus): PP対象として許可するbeatmap status.

    Returns:
        None: eligibilityがTrueで除外reasonがないことを検証して完了する.

    Raises:
        AssertionError: 対象statusのpassed vanilla scoreを除外した場合.
    """
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
    """Ranked scope外のbeatmap statusをmachine-readable reason付きで除外することを検証する.

    Args:
        status (BeatmapRankStatus): PP対象外として扱うbeatmap status.
        reason (str): 期待する除外reason.

    Returns:
        None: eligibility否定と固定reasonを検証して完了する.

    Raises:
        AssertionError: scope外statusを受理するかreasonが変わった場合.
    """
    decision = PerformanceEligibilityPolicy().evaluate(_make_score(status=status))

    assert not decision.is_eligible
    assert decision.reason == reason


def test_failed_score_is_out_of_scope() -> None:
    """Failed scoreをranked PP scopeからscore_failed reasonで除外することを検証する.

    Returns:
        None: eligibility否定とscore_failed reasonを検証して完了する.

    Raises:
        AssertionError: failed scoreをPP対象にした場合.
    """
    decision = PerformanceEligibilityPolicy().evaluate(_make_score(passed=False))

    assert not decision.is_eligible
    assert decision.reason == "score_failed"


def test_submission_ineligible_score_is_out_of_scope() -> None:
    """submit時にleaderboard対象外だったscoreをbest candidateから除外することを検証する.

    Returns:
        None: eligibility否定とscore_not_eligible reasonを検証して完了する.

    Raises:
        AssertionError: submit eligibilityを無視してcandidateを受理した場合.
    """
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
    """RELAXまたはAUTOPILOT modのscoreをplaystyle scope外として除外することを検証する.

    Args:
        mods (ModCombination): scope外playstyleを表すmod組合せ.
        reason (str): 期待する除外reason.

    Returns:
        None: eligibility否定と固定reasonを検証して完了する.

    Raises:
        AssertionError: scope外playstyleをPP対象にした場合.
    """
    decision = PerformanceEligibilityPolicy().evaluate(_make_score(mods=mods))

    assert not decision.is_eligible
    assert decision.reason == reason


def test_missing_beatmap_status_is_out_of_scope() -> None:
    """submit時のbeatmap statusがないscoreをPP対象外にすることを検証する.

    Returns:
        None: eligibility否定とbeatmap_status_missing reasonを検証して完了する.

    Raises:
        AssertionError: status不明scoreをPP対象にした場合.
    """
    decision = PerformanceEligibilityPolicy().evaluate(_make_score(status=None))

    assert not decision.is_eligible
    assert decision.reason == "beatmap_status_missing"


def test_formula_profile_policy_returns_one_profile_per_playstyle() -> None:
    """VANILLA playstyleに現行VANILLA_RANKED formula profileだけを対応付けることを検証する.

    Returns:
        None: active profileのidentityを検証して完了する.

    Raises:
        AssertionError: VANILLAのactive formula profileが変わった場合.
    """
    policy = FormulaProfilePolicy()

    assert policy.active_profile_for(Playstyle.VANILLA) is FormulaProfile.VANILLA_RANKED


def test_future_loved_relax_and_autopilot_pp_scopes_remain_disabled() -> None:
    """未採用のLOVED, RELAX, AUTOPILOT PP scopeが明示的に無効なままであることを検証する.

    Returns:
        None: profile mappingと三つのeligibility否定を検証して完了する.

    Raises:
        AssertionError: 将来用scopeを意図せず有効化した場合.
    """
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
    """FormulaProfilePolicyが未知objectをplaystyleとして受理しないことを検証する.

    Returns:
        None: 未知入力がValueErrorになることを検証して完了する.

    Raises:
        AssertionError: 型外のplaystyle objectをprofileへ対応付けた場合.
    """
    policy = FormulaProfilePolicy()

    with pytest.raises(ValueError, match="unsupported playstyle"):
        _ = policy.active_profile_for(object())
