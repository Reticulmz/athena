"""Stable client 固有の grade compatibility vocabulary を定義する module."""

from enum import IntEnum


class StableGrade(IntEnum):
    """Stable client 固有の 1-byte grade wire 値を表す enum.

    Attributes:
        XH (StableGrade): 0 を表す Stable grade wire 値.
        SH (StableGrade): 1 を表す Stable grade wire 値.
        X (StableGrade): 2 を表す Stable grade wire 値.
        S (StableGrade): 3 を表す Stable grade wire 値.
        A (StableGrade): 4 を表す Stable grade wire 値.
        B (StableGrade): 5 を表す Stable grade wire 値.
        C (StableGrade): 6 を表す Stable grade wire 値.
        D (StableGrade): 7 を表す Stable grade wire 値.
        F (StableGrade): 8 を表す Stable grade wire 値.
        N (StableGrade): 9 を表す Stable grade wire 値.

    Notes:
        BeatmapInfo の grade field 用 vocabulary であり canonical score grade ではない.
        Score grade の計算, 変換, 集計, projection はこの型の責務に含めない.
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
