"""Stable client play mode enum values."""

from enum import IntEnum


class StableMode(IntEnum):
    """Stable client の Mode wire 値を表す。"""

    Osu = 0
    Taiko = 1
    Fruits = 2
    Mania = 3


__all__ = ["StableMode"]
