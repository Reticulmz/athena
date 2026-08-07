"""Score domain modelの値保持と最小invariantを検証する."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score


def test_score_creation_with_all_fields() -> None:
    """Scoreが全必須fieldとsubmit時beatmap statusを保持することを検証する.

    Returns:
        None: 構築後の主要識別子, enum, statusを検証して完了する.

    Raises:
        AssertionError: Scoreが受理したfieldを保持しない場合.
    """
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
        beatmap_status_at_submission=BeatmapRankStatus.RANKED,
    )

    assert score.id == 1
    assert score.user_id == 100
    assert score.ruleset == Ruleset.OSU
    assert score.playstyle == Playstyle.VANILLA
    assert score.grade == Grade.A
    assert score.beatmap_status_at_submission is BeatmapRankStatus.RANKED


def test_score_without_id() -> None:
    """未永続化ScoreがID未割当のNoneを保持できることを検証する.

    Returns:
        None: None IDを持つScoreの構築を検証して完了する.

    Raises:
        AssertionError: 未永続化ScoreをIDなしで表現できない場合.
    """
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


def test_score_replay_view_count_defaults_to_zero() -> None:
    """replay_view_count未指定のScoreが初期値0を持つことを検証する.

    Returns:
        None: default replay view countが0であることを検証して完了する.

    Raises:
        AssertionError: 未指定時の閲覧回数初期値が0以外の場合.
    """
    score = _score()

    assert score.replay_view_count == 0


def test_score_replay_view_count_rejects_null() -> None:
    """Scoreがnull replay_view_countをValueErrorで拒否することを検証する.

    Returns:
        None: null値でのreplaceがValueErrorになることを検証して完了する.

    Raises:
        AssertionError: null閲覧回数を有効なScore状態として受理した場合.
    """
    with pytest.raises(ValueError, match="replay_view_count cannot be null"):
        _ = replace(_score(), replay_view_count=cast("int", cast("object", None)))


def test_score_replay_view_count_rejects_negative_value() -> None:
    """Scoreが負のreplay_view_countをValueErrorで拒否することを検証する.

    Returns:
        None: 負数でのreplaceがValueErrorになることを検証して完了する.

    Raises:
        AssertionError: 負の閲覧回数を有効なScore状態として受理した場合.
    """
    with pytest.raises(ValueError, match="replay_view_count must be non-negative"):
        _ = replace(_score(), replay_view_count=-1)


def test_ruleset_enum_values() -> None:
    """Rulesetがosu, taiko, catch, maniaの固定protocol valueを持つことを検証する.

    Returns:
        None: 各Ruleset memberの整数valueを検証して完了する.

    Raises:
        AssertionError: rulesetの固定整数valueが変更された場合.
    """
    assert Ruleset.OSU.value == 0
    assert Ruleset.TAIKO.value == 1
    assert Ruleset.CATCH.value == 2
    assert Ruleset.MANIA.value == 3


def test_playstyle_enum_values() -> None:
    """Playstyleがcurrent scopeのVANILLA固定valueを持つことを検証する.

    Returns:
        None: VANILLAの整数valueを検証して完了する.

    Raises:
        AssertionError: current scopeのplaystyle valueが変更された場合.
    """
    assert Playstyle.VANILLA.value == 0


def test_grade_enum_values() -> None:
    """Gradeがcanonical result codeの閉じた文字列集合を持つことを検証する.

    Returns:
        None: 各Grade memberの固定文字列valueを検証して完了する.

    Raises:
        AssertionError: grade codeの追加, 欠落またはvalue変更があった場合.
    """
    assert Grade.XH.value == "XH"
    assert Grade.X.value == "X"
    assert Grade.SH.value == "SH"
    assert Grade.S.value == "S"
    assert Grade.A.value == "A"
    assert Grade.B.value == "B"
    assert Grade.C.value == "C"
    assert Grade.D.value == "D"


def _score() -> Score:
    """Replay view count invariant検証用の有効なScoreを作成する.

    Returns:
        Score: default値以外を固定した有効なscore.
    """
    return Score(
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
        beatmap_status_at_submission=BeatmapRankStatus.RANKED,
    )
