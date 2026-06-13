"""Unit tests for Score domain model."""

from datetime import UTC, datetime

from osu_server.domain.score.score import Grade, Playstyle, Ruleset, Score
from osu_server.domain.scores.mods import ModCombination


def test_score_creation_with_all_fields() -> None:
    """Score dataclassが全フィールドを受け入れる。"""
    score = Score(
        id=1,
        user_id=100,
        beatmap_id=200,
        beatmap_checksum="abc123",
        online_checksum="xyz789",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
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
        passed=True,
        perfect=False,
        client_version="b20250101",
        submitted_at=datetime(2026, 6, 11, 0, 0, 0, tzinfo=UTC),
        beatmap_status_at_submission="ranked",
    )

    assert score.id == 1
    assert score.user_id == 100
    assert score.ruleset == Ruleset.OSU
    assert score.playstyle == Playstyle.VANILLA
    assert score.grade == Grade.A
    assert score.beatmap_status_at_submission == "ranked"


def test_score_without_id() -> None:
    """ID未割り当て(None)のScoreを作成できる。"""
    score = Score(
        id=None,
        user_id=100,
        beatmap_id=200,
        beatmap_checksum="abc",
        online_checksum="xyz",
        ruleset=Ruleset.TAIKO,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=0,
        n100=0,
        n50=0,
        geki=0,
        katu=0,
        miss=0,
        score=0,
        max_combo=0,
        accuracy=0.0,
        grade=Grade.D,
        passed=False,
        perfect=False,
        client_version="b20250101",
        submitted_at=datetime.now(UTC),
    )

    assert score.id is None


def test_ruleset_enum_values() -> None:
    """Rulesetがosu/taiko/catch/maniaをサポート。"""
    assert Ruleset.OSU.value == 0
    assert Ruleset.TAIKO.value == 1
    assert Ruleset.CATCH.value == 2
    assert Ruleset.MANIA.value == 3


def test_playstyle_enum_values() -> None:
    """PlaystyleがVANILLA(Wave 1 scope)をサポート。"""
    assert Playstyle.VANILLA.value == 0


def test_grade_enum_values() -> None:
    """GradeがXH/X/SH/S/A/B/C/Dをサポート。"""
    assert Grade.XH.value == "XH"
    assert Grade.X.value == "X"
    assert Grade.SH.value == "SH"
    assert Grade.S.value == "S"
    assert Grade.A.value == "A"
    assert Grade.B.value == "B"
    assert Grade.C.value == "C"
    assert Grade.D.value == "D"
