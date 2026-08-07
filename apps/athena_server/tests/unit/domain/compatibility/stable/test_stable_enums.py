"""Stable compatibility enumの固定wire valueを検証する."""

from enum import IntEnum

from osu_server.domain.compatibility.stable import (
    StableGrade,
    StableMode,
    StablePresenceFilter,
    StableStatus,
)
from osu_server.domain.compatibility.stable.grade import (
    StableGrade as StableGradeDefinition,
)


def test_stable_status_values_match_guide() -> None:
    """Stable status enumがprotocol guideのmember順と整数値を保持することを検証する.

    Returns:
        None: status member集合の完全一致を検証して完了する.

    Raises:
        AssertionError: statusのmember名, 順序またはwire valueが変更された場合.
    """
    members = [(member.name, member.value) for member in StableStatus]

    assert members == [
        ("Idle", 0),
        ("Afk", 1),
        ("Playing", 2),
        ("Editing", 3),
        ("Modding", 4),
        ("Multiplayer", 5),
        ("Watching", 6),
        ("Unknown", 7),
        ("Testing", 8),
        ("Submitting", 9),
        ("Paused", 10),
        ("Lobby", 11),
        ("Multiplaying", 12),
        ("OsuDirect", 13),
    ]


def test_stable_mode_values_match_guide() -> None:
    """Stable mode enumがprotocol guideのmember順と整数値を保持することを検証する.

    Returns:
        None: mode member集合の完全一致を検証して完了する.

    Raises:
        AssertionError: modeのmember名, 順序またはwire valueが変更された場合.
    """
    members = [(member.name, member.value) for member in StableMode]

    assert members == [
        ("Osu", 0),
        ("Taiko", 1),
        ("Fruits", 2),
        ("Mania", 3),
    ]


def test_stable_presence_filter_values_match_guide() -> None:
    """Stable presence filter enumがprotocol guideの固定値を保持することを検証する.

    Returns:
        None: presence filter member集合の完全一致を検証して完了する.

    Raises:
        AssertionError: filterのmember名, 順序またはwire valueが変更された場合.
    """
    members = [(member.name, member.value) for member in StablePresenceFilter]

    assert members == [
        ("NoPlayers", 0),
        ("All", 1),
        ("Friends", 2),
    ]


def test_stable_grade_is_exact_closed_int_enum() -> None:
    """StableGradeがaliasを含まない閉じたIntEnumとして固定wire語彙を持つことを検証する.

    Returns:
        None: member名, 順序, 値, 型を検証して完了する.

    Raises:
        AssertionError: StableGradeが設計済みのmember, 順序, 値, 型を満たさない場合.

    Notes:
        __members__を使い, iterationでは見えないaliasも検証対象に含める.
    """
    members = [
        (member_name, member.value) for member_name, member in StableGrade.__members__.items()
    ]

    assert issubclass(StableGrade, IntEnum)
    assert members == [
        ("XH", 0),
        ("SH", 1),
        ("X", 2),
        ("S", 3),
        ("A", 4),
        ("B", 5),
        ("C", 6),
        ("D", 7),
        ("F", 8),
        ("N", 9),
    ]


def test_stable_grade_is_reexported_from_stable_package() -> None:
    """StableGradeがstable package rootからdefinitionと同一の型として公開されることを検証する.

    Returns:
        None: package rootの再公開が同一型であることを検証して完了する.

    Raises:
        AssertionError: package rootの再公開が欠けるか別の型を公開している場合.

    Notes:
        transportはpackage rootのstable compatibility vocabularyだけを参照する.
    """
    assert StableGrade is StableGradeDefinition
