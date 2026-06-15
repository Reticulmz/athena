"""Canonical score mod domain language."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag
from typing import Self


class Mod(IntFlag):
    """Canonical mod flags shared by score workflows."""

    NONE = 0
    NO_FAIL = 1 << 0
    EASY = 1 << 1
    TOUCH_DEVICE = 1 << 2
    HIDDEN = 1 << 3
    HARD_ROCK = 1 << 4
    SUDDEN_DEATH = 1 << 5
    DOUBLE_TIME = 1 << 6
    RELAX = 1 << 7
    HALF_TIME = 1 << 8
    NIGHTCORE = 1 << 9
    FLASHLIGHT = 1 << 10
    AUTOPLAY = 1 << 11
    SPUN_OUT = 1 << 12
    AUTOPILOT = 1 << 13
    PERFECT = 1 << 14
    KEY4 = 1 << 15
    KEY5 = 1 << 16
    KEY6 = 1 << 17
    KEY7 = 1 << 18
    KEY8 = 1 << 19
    FADE_IN = 1 << 20
    RANDOM = 1 << 21
    CINEMA = 1 << 22
    TARGET_PRACTICE = 1 << 23
    KEY9 = 1 << 24
    KEY_COOP = 1 << 25
    KEY1 = 1 << 26
    KEY3 = 1 << 27
    KEY2 = 1 << 28
    SCORE_V2 = 1 << 29
    MIRROR = 1 << 30


@dataclass(frozen=True, slots=True)
class ModCombination:
    """Canonical immutable mod combination value object."""

    mods: Mod = Mod.NONE

    @classmethod
    def none(cls) -> Self:
        return cls(Mod.NONE)

    @classmethod
    def from_bitmask(cls, bitmask: int) -> Self:
        if bitmask < 0:
            msg = "mod bitmask must be non-negative"
            raise ValueError(msg)
        return cls(Mod(bitmask))

    @classmethod
    def from_persistence_bitmask(cls, bitmask: int) -> Self:
        return cls.from_bitmask(bitmask)

    def has(self, mod: Mod) -> bool:
        return (self.mods & mod) == mod

    def to_persistence_bitmask(self) -> int:
        return int(self.mods)

    def unsupported_bits(self, supported_mods: Mod) -> int:
        return self.to_persistence_bitmask() & ~int(supported_mods)

    def __contains__(self, mod: Mod) -> bool:
        return self.has(mod)

    def __int__(self) -> int:
        return self.to_persistence_bitmask()


__all__ = ["Mod", "ModCombination"]
