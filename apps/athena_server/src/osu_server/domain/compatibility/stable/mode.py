"""Stable client play mode の compatibility enum を定義する module."""

from enum import IntEnum


class StableMode(IntEnum):
    """Stable client の Mode wire 値を表す enum.

    Attributes:
        Osu (StableMode): osu! standard mode の wire 値0.
        Taiko (StableMode): osu!taiko mode の wire 値1.
        Fruits (StableMode): osu!catch mode の wire 値2.
        Mania (StableMode): osu!mania mode の wire 値3.
    """

    Osu = 0
    Taiko = 1
    Fruits = 2
    Mania = 3


__all__ = ["StableMode"]
