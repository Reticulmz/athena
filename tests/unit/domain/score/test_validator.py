"""Unit tests for Score Validator."""

import pytest

from osu_server.domain.score.payload_parser import ParsedScore
from osu_server.domain.score.score import Grade, Ruleset
from osu_server.domain.score.validator import (
    ValidationError,
    validate_hit_counts,
)
from osu_server.domain.scores.mods import ModCombination


def test_validate_osu_standard_valid() -> None:
    """osu! standard ruleset の valid hit counts を受け入れる。"""
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
    """osu! ruleset の accuracy を正しく計算する。"""
    # 300=100, 100=0, 50=0, miss=0 => 100% accuracy
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
    """osu! ruleset で SS grade を正しく計算する。"""
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
    """osu! ruleset で S grade を正しく計算する。"""
    # Accuracy > 90%, no miss
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
    """osu! ruleset で A grade を正しく計算する。"""
    # Accuracy > 80%
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
    """taiko ruleset の valid hit counts を受け入れる。"""
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
    """taiko ruleset で n50 が無視されることを確認する。"""
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
    """catch ruleset の valid hit counts を受け入れる。"""
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
    """mania ruleset の valid hit counts を受け入れる。"""
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
    """全ての hit counts が 0 の場合 ValidationError を発生させる。"""
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
    """Negative hit counts で ValidationError を発生させる。"""
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
    """Unknown ruleset で ValidationError を発生させる。"""
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
