"""Canonical mod と Stable client bitmask の compatibility mapping を定義する module."""

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
    """Stable client が表現できる mod flag の union を構築する.

    Returns:
        Mod: Stable compatibility boundary が受け入れる mod flag の組合せ.

    Notes:
        Module import 時に一度だけ評価して _STABLE_SUPPORTED_MODS に保持する.
    """
    supported = Mod.NONE
    for mod in _STABLE_SUPPORTED_MOD_FLAGS:
        supported |= mod
    return supported


_STABLE_SUPPORTED_MODS = _stable_supported_mods()


class StableModMappingStatus(StrEnum):
    """Canonical mod combination の Stable mapping outcome を表す enum.

    Attributes:
        SUPPORTED (StableModMappingStatus): Stable bitmask へ完全に変換できる結果.
        UNSUPPORTED (StableModMappingStatus): Stable 未対応 bit を含む結果.
    """

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class StableModMappingResult:
    """Canonical mod combination を Stable client 表現へ変換した結果を表す value object.

    Attributes:
        status (StableModMappingStatus): mapping の成功または未対応結果.
        bitmask (int | None): 完全変換できた場合の Stable legacy mod bitmask.
            未対応 bit がある場合はNone.
        unsupported_bits (int): Stable client が表現できない canonical mod bit 群.
    """

    status: StableModMappingStatus
    bitmask: int | None
    unsupported_bits: int = 0

    @property
    def is_supported(self) -> bool:
        """Mapping が Stable client で完全に表現できるか返す.

        Returns:
            bool: status が SUPPORTED の場合はTrue.
        """
        return self.status == StableModMappingStatus.SUPPORTED


def stable_mod_bitmask_to_mod_combination(bitmask: int) -> ModCombination:
    """Stable client bitmask を対応済み canonical mod combination へ変換する.

    Args:
        bitmask (int): Stable wire から受信した非負の legacy mod bitmask.

    Returns:
        ModCombination: Stable で対応済みの canonical mod combination.

    Raises:
        ValueError: bitmask が負数または Stable 未対応 bit を含む場合.
    """
    mods = ModCombination.from_bitmask(bitmask)
    unsupported_bits = mods.unsupported_bits(_STABLE_SUPPORTED_MODS)
    if unsupported_bits:
        msg = f"stable mod bitmask contains unsupported bits: {unsupported_bits}"
        raise ValueError(msg)
    return mods


def mod_combination_to_stable_bitmask(mods: ModCombination) -> StableModMappingResult:
    """Canonical mod combination を Stable bitmask へ変換する.

    Args:
        mods (ModCombination): Stable client 表現へ変換する canonical mod combination.

    Returns:
        StableModMappingResult: 成功時の bitmask または未対応 bit 群を持つ mapping 結果.
    """
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
