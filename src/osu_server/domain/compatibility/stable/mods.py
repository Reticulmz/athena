"""Stable mod compatibility mapping."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from osu_server.domain.scores.mods import Mod, ModCombination

_STABLE_SUPPORTED_MOD_FLAGS = (
    Mod.NO_FAIL,
    Mod.EASY,
    Mod.TOUCH_DEVICE,
    Mod.HIDDEN,
    Mod.HARD_ROCK,
    Mod.SUDDEN_DEATH,
    Mod.DOUBLE_TIME,
    Mod.RELAX,
    Mod.HALF_TIME,
    Mod.NIGHTCORE,
    Mod.FLASHLIGHT,
    Mod.AUTOPLAY,
    Mod.SPUN_OUT,
    Mod.AUTOPILOT,
    Mod.PERFECT,
    Mod.KEY4,
    Mod.KEY5,
    Mod.KEY6,
    Mod.KEY7,
    Mod.KEY8,
    Mod.FADE_IN,
    Mod.RANDOM,
    Mod.CINEMA,
    Mod.TARGET_PRACTICE,
    Mod.KEY9,
    Mod.KEY_COOP,
    Mod.KEY1,
    Mod.KEY3,
    Mod.KEY2,
    Mod.SCORE_V2,
    Mod.MIRROR,
)


def _stable_supported_mods() -> Mod:
    supported = Mod.NONE
    for mod in _STABLE_SUPPORTED_MOD_FLAGS:
        supported |= mod
    return supported


_STABLE_SUPPORTED_MODS = _stable_supported_mods()


class StableModMappingStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class StableModMappingResult:
    """Stable client representation result for a canonical mod combination."""

    status: StableModMappingStatus
    bitmask: int | None
    unsupported_bits: int = 0

    @property
    def is_supported(self) -> bool:
        return self.status == StableModMappingStatus.SUPPORTED


def stable_mod_bitmask_to_mod_combination(bitmask: int) -> ModCombination:
    """stable client bitmaskを対応済みMod combinationへ変換する.

    Args:
        bitmask (int): stable wireから受信した非負のlegacy Mod bitmask.

    Returns:
        ModCombination: stableで対応済みのMod combination.

    Raises:
        ValueError: bitmaskが負数またはstable未対応bitを含む場合.
    """
    mods = ModCombination.from_bitmask(bitmask)
    unsupported_bits = mods.unsupported_bits(_STABLE_SUPPORTED_MODS)
    if unsupported_bits:
        msg = f"stable mod bitmask contains unsupported bits: {unsupported_bits}"
        raise ValueError(msg)
    return mods


def mod_combination_to_stable_bitmask(mods: ModCombination) -> StableModMappingResult:
    """Convert canonical mods to stable bitmask or report unsupported bits."""
    unsupported_bits = mods.unsupported_bits(_STABLE_SUPPORTED_MODS)
    if unsupported_bits:
        return StableModMappingResult(
            status=StableModMappingStatus.UNSUPPORTED,
            bitmask=None,
            unsupported_bits=unsupported_bits,
        )

    return StableModMappingResult(
        status=StableModMappingStatus.SUPPORTED,
        bitmask=mods.to_persistence_bitmask(),
    )


__all__ = [
    "StableModMappingResult",
    "StableModMappingStatus",
    "mod_combination_to_stable_bitmask",
    "stable_mod_bitmask_to_mod_combination",
]
