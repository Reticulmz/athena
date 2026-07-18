"""Stable client 固有の grade compatibility vocabulary。"""

from enum import IntEnum


class StableGrade(IntEnum):
    """Stable client 固有の 1-byte grade wire 値を表す。

    BeatmapInfo の grade field で使う stable compatibility vocabulary であり、
    canonical score grade ではない。score grade の計算、変換、集計、projection は
    この型の責務に含めない。

    Args:
        value (int): 復元する stable grade の wire 値。

    Returns:
        StableGrade: 対応する stable grade member。

    Raises:
        ValueError: value が定義済みの stable grade wire 値に対応しない場合。

    Attributes:
        XH (StableGrade): 0 を表す stable grade wire 値。
        SH (StableGrade): 1 を表す stable grade wire 値。
        X (StableGrade): 2 を表す stable grade wire 値。
        S (StableGrade): 3 を表す stable grade wire 値。
        A (StableGrade): 4 を表す stable grade wire 値。
        B (StableGrade): 5 を表す stable grade wire 値。
        C (StableGrade): 6 を表す stable grade wire 値。
        D (StableGrade): 7 を表す stable grade wire 値。
        F (StableGrade): 8 を表す stable grade wire 値。
        N (StableGrade): 9 を表す stable grade wire 値。

    Constraints:
        値集合は stable client の wire vocabulary として閉じており、alias、default
        member、core score grade への依存を追加してはならない。
    """

    XH = 0
    SH = 1
    X = 2
    S = 3
    A = 4
    B = 5
    C = 6
    D = 7
    F = 8
    N = 9


__all__ = ["StableGrade"]
