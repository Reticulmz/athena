"""Stable compatibility enum value tests."""

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
    members = [(member.name, member.value) for member in StableMode]

    assert members == [
        ("Osu", 0),
        ("Taiko", 1),
        ("Fruits", 2),
        ("Mania", 3),
    ]


def test_stable_presence_filter_values_match_guide() -> None:
    members = [(member.name, member.value) for member in StablePresenceFilter]

    assert members == [
        ("NoPlayers", 0),
        ("All", 1),
        ("Friends", 2),
    ]


def test_stable_grade_is_exact_closed_int_enum() -> None:
    """StableGrade の宣言順、wire 値、閉集合性を検証する。

    Returns:
        None: pytest assertion により検証結果を表す。

    Raises:
        AssertionError: StableGrade が設計済みの member、順序、値、型を満たさない場合。

    Constraints:
        __members__ を使い、iteration では見えない alias も検証対象に含める。
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
    """StableGrade が stable package root から同じ型として公開されることを検証する。

    Returns:
        None: pytest assertion により検証結果を表す。

    Raises:
        AssertionError: package root の再公開が欠けるか別の型を公開している場合。

    Constraints:
        transport は package root の stable compatibility vocabulary のみを参照する。
    """
    assert StableGrade is StableGradeDefinition
