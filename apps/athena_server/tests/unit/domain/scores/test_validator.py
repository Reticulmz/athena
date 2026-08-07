"""Score hit count validatorのruleset別計算とreject契約を検証する."""

import pytest

from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.payload_parser import ParsedScore
from osu_server.domain.scores.score import Grade, Ruleset
from osu_server.domain.scores.validator import (
    ValidationError,
    validate_hit_counts,
)


def test_validate_osu_standard_valid() -> None:
    """Osu! standardの整合したhit countをvalid resultとして受理することを検証する.

    Returns:
        None: valid flag, 正のaccuracy, 既知Gradeを検証して完了する.

    Raises:
        AssertionError: 整合したosu! standard inputを拒否するか不正なresultを返した場合.
    """
    parsed = ParsedScore(
        user_id=100,
        username="test",
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=Ruleset.OSU.value,
        mods=ModCombination.none(),
        n300=300,
        n100=50,
        n50=10,
        geki=0,
        katu=0,
        miss=5,
        score=500000,
        max_combo=350,
        perfect=False,
        passed=True,
    )

    result = validate_hit_counts(parsed)

    assert result.valid is True
    assert result.accuracy > 0.0
    assert result.grade in list(Grade)


def test_validate_osu_accuracy_calculation() -> None:
    """Osu! standardの全300判定をaccuracy 1.0として計算することを検証する.

    Returns:
        None: valid resultと1.0近傍のaccuracyを検証して完了する.

    Raises:
        AssertionError: 全300判定のaccuracy計算が1.0から外れた場合.
    """
    parsed = ParsedScore(
        user_id=100,
        username="test",
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=Ruleset.OSU.value,
        mods=ModCombination.none(),
        n300=100,
        n100=0,
        n50=0,
        geki=0,
        katu=0,
        miss=0,
        score=1000000,
        max_combo=100,
        perfect=True,
        passed=True,
    )

    result = validate_hit_counts(parsed)

    assert result.valid is True
    assert result.accuracy == pytest.approx(1.0, abs=0.01)  # pyright: ignore[reportUnknownMemberType]


def test_validate_osu_grade_ss() -> None:
    """Osu! standardのperfect全300判定をGrade.Xとして分類することを検証する.

    Returns:
        None: result gradeがGrade.Xであることを検証して完了する.

    Raises:
        AssertionError: perfect全300判定のgrade分類が変わった場合.
    """
    parsed = ParsedScore(
        user_id=100,
        username="test",
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=Ruleset.OSU.value,
        mods=ModCombination.none(),
        n300=100,
        n100=0,
        n50=0,
        geki=0,
        katu=0,
        miss=0,
        score=1000000,
        max_combo=100,
        perfect=True,
        passed=True,
    )

    result = validate_hit_counts(parsed)

    assert result.grade == Grade.X


def test_validate_osu_grade_s() -> None:
    """Osu! standardの90%超かつmissなしのinputをGrade.Sとして分類することを検証する.

    Returns:
        None: result gradeがGrade.Sであることを検証して完了する.

    Raises:
        AssertionError: S grade閾値またはmiss条件の分類が変わった場合.
    """
    parsed = ParsedScore(
        user_id=100,
        username="test",
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=Ruleset.OSU.value,
        mods=ModCombination.none(),
        n300=95,
        n100=5,
        n50=0,
        geki=0,
        katu=0,
        miss=0,
        score=950000,
        max_combo=100,
        perfect=False,
        passed=True,
    )

    result = validate_hit_counts(parsed)

    assert result.grade == Grade.S


def test_validate_osu_grade_a() -> None:
    """Osu! standardの80%超inputをGrade.Aとして分類することを検証する.

    Returns:
        None: result gradeがGrade.Aであることを検証して完了する.

    Raises:
        AssertionError: A gradeのaccuracy閾値による分類が変わった場合.
    """
    parsed = ParsedScore(
        user_id=100,
        username="test",
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=Ruleset.OSU.value,
        mods=ModCombination.none(),
        n300=85,
        n100=10,
        n50=5,
        geki=0,
        katu=0,
        miss=0,
        score=850000,
        max_combo=100,
        perfect=False,
        passed=True,
    )

    result = validate_hit_counts(parsed)

    assert result.grade == Grade.A


def test_validate_taiko_valid() -> None:
    """taikoの整合したhit countをvalid resultとして受理することを検証する.

    Returns:
        None: valid flagと正のaccuracyを検証して完了する.

    Raises:
        AssertionError: 整合したtaiko inputを拒否するか不正なresultを返した場合.
    """
    parsed = ParsedScore(
        user_id=100,
        username="test",
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=Ruleset.TAIKO.value,
        mods=ModCombination.none(),
        n300=200,
        n100=50,
        n50=0,
        geki=0,
        katu=0,
        miss=10,
        score=400000,
        max_combo=200,
        perfect=False,
        passed=True,
    )

    result = validate_hit_counts(parsed)

    assert result.valid is True
    assert result.accuracy > 0.0


def test_validate_taiko_ignores_n50() -> None:
    """Taiko accuracy計算がn50を無視して全300判定を1.0と扱うことを検証する.

    Returns:
        None: 大きなn50でもvalid resultと1.0近傍accuracyを検証して完了する.

    Raises:
        AssertionError: taikoのaccuracy計算がn50を考慮した場合.
    """
    parsed = ParsedScore(
        user_id=100,
        username="test",
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=Ruleset.TAIKO.value,
        mods=ModCombination.none(),
        n300=100,
        n100=0,
        n50=999,  # Should be ignored
        geki=0,
        katu=0,
        miss=0,
        score=1000000,
        max_combo=100,
        perfect=True,
        passed=True,
    )

    result = validate_hit_counts(parsed)

    assert result.valid is True
    assert result.accuracy == pytest.approx(1.0, abs=0.01)  # pyright: ignore[reportUnknownMemberType]


def test_validate_catch_valid() -> None:
    """catchの整合したhit countをvalid resultとして受理することを検証する.

    Returns:
        None: valid flagと正のaccuracyを検証して完了する.

    Raises:
        AssertionError: 整合したcatch inputを拒否するか不正なresultを返した場合.
    """
    parsed = ParsedScore(
        user_id=100,
        username="test",
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=Ruleset.CATCH.value,
        mods=ModCombination.none(),
        n300=300,
        n100=50,
        n50=20,
        geki=0,
        katu=10,
        miss=5,
        score=500000,
        max_combo=350,
        perfect=False,
        passed=True,
    )

    result = validate_hit_counts(parsed)

    assert result.valid is True
    assert result.accuracy > 0.0


def test_validate_mania_valid() -> None:
    """maniaの整合したhit countをvalid resultとして受理することを検証する.

    Returns:
        None: valid flagと正のaccuracyを検証して完了する.

    Raises:
        AssertionError: 整合したmania inputを拒否するか不正なresultを返した場合.
    """
    parsed = ParsedScore(
        user_id=100,
        username="test",
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=Ruleset.MANIA.value,
        mods=ModCombination.none(),
        n300=300,
        n100=50,
        n50=20,
        geki=100,
        katu=20,
        miss=5,
        score=900000,
        max_combo=350,
        perfect=False,
        passed=True,
    )

    result = validate_hit_counts(parsed)

    assert result.valid is True
    assert result.accuracy > 0.0


def test_validate_inconsistent_hit_counts_all_zero() -> None:
    """全hit countが0のinconsistent inputをValidationErrorで拒否することを検証する.

    Returns:
        None: exception messageにhit countが含まれることを検証して完了する.

    Raises:
        AssertionError: 全ゼロhit countをvalid scoreとして受理するかdiagnosticを失った場合.
    """
    parsed = ParsedScore(
        user_id=100,
        username="test",
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=Ruleset.OSU.value,
        mods=ModCombination.none(),
        n300=0,
        n100=0,
        n50=0,
        geki=0,
        katu=0,
        miss=0,
        score=0,
        max_combo=0,
        perfect=False,
        passed=True,
    )

    with pytest.raises(ValidationError) as exc_info:
        _ = validate_hit_counts(parsed)

    assert "hit count" in str(exc_info.value).lower()


def test_validate_negative_hit_counts() -> None:
    """負のhit countをValidationErrorで拒否することを検証する.

    Returns:
        None: exception messageにnegativeが含まれることを検証して完了する.

    Raises:
        AssertionError: 負の判定数をvalid scoreとして受理するかdiagnosticを失った場合.
    """
    parsed = ParsedScore(
        user_id=100,
        username="test",
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=Ruleset.OSU.value,
        mods=ModCombination.none(),
        n300=-1,
        n100=50,
        n50=10,
        geki=0,
        katu=0,
        miss=0,
        score=500000,
        max_combo=350,
        perfect=False,
        passed=True,
    )

    with pytest.raises(ValidationError) as exc_info:
        _ = validate_hit_counts(parsed)

    assert "negative" in str(exc_info.value).lower()


def test_validate_unknown_ruleset() -> None:
    """未知のruleset整数値をValidationErrorで拒否することを検証する.

    Returns:
        None: exception messageにrulesetが含まれることを検証して完了する.

    Raises:
        AssertionError: 未知rulesetをvalid scoreとして受理するかdiagnosticを失った場合.
    """
    parsed = ParsedScore(
        user_id=100,
        username="test",
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=99,  # Invalid
        mods=ModCombination.none(),
        n300=100,
        n100=0,
        n50=0,
        geki=0,
        katu=0,
        miss=0,
        score=1000000,
        max_combo=100,
        perfect=True,
        passed=True,
    )

    with pytest.raises(ValidationError) as exc_info:
        _ = validate_hit_counts(parsed)

    assert "ruleset" in str(exc_info.value).lower()
