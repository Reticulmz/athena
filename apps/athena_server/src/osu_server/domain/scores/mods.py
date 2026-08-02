"""score workflow で共通に使う canonical mod domain 値を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag
from typing import Self


class Mod(IntFlag):
    """score workflow 間で共有する canonical な mod bit flag を表す.

    Attributes:
        NONE (Mod): mod 未指定を表す固定値 0.
        NO_FAIL (Mod): `NO_FAIL` を表す固定 bit `1 << 0`.
        EASY (Mod): `EASY` を表す固定 bit `1 << 1`.
        TOUCH_DEVICE (Mod): `TOUCH_DEVICE` を表す固定 bit `1 << 2`.
        HIDDEN (Mod): `HIDDEN` を表す固定 bit `1 << 3`.
        HARD_ROCK (Mod): `HARD_ROCK` を表す固定 bit `1 << 4`.
        SUDDEN_DEATH (Mod): `SUDDEN_DEATH` を表す固定 bit `1 << 5`.
        DOUBLE_TIME (Mod): `DOUBLE_TIME` を表す固定 bit `1 << 6`.
        RELAX (Mod): `RELAX` を表す固定 bit `1 << 7`.
        HALF_TIME (Mod): `HALF_TIME` を表す固定 bit `1 << 8`.
        NIGHTCORE (Mod): `NIGHTCORE` を表す固定 bit `1 << 9`.
        FLASHLIGHT (Mod): `FLASHLIGHT` を表す固定 bit `1 << 10`.
        AUTOPLAY (Mod): `AUTOPLAY` を表す固定 bit `1 << 11`.
        SPUN_OUT (Mod): `SPUN_OUT` を表す固定 bit `1 << 12`.
        AUTOPILOT (Mod): `AUTOPILOT` を表す固定 bit `1 << 13`.
        PERFECT (Mod): `PERFECT` を表す固定 bit `1 << 14`.
        KEY4 (Mod): `KEY4` を表す固定 bit `1 << 15`.
        KEY5 (Mod): `KEY5` を表す固定 bit `1 << 16`.
        KEY6 (Mod): `KEY6` を表す固定 bit `1 << 17`.
        KEY7 (Mod): `KEY7` を表す固定 bit `1 << 18`.
        KEY8 (Mod): `KEY8` を表す固定 bit `1 << 19`.
        FADE_IN (Mod): `FADE_IN` を表す固定 bit `1 << 20`.
        RANDOM (Mod): `RANDOM` を表す固定 bit `1 << 21`.
        CINEMA (Mod): `CINEMA` を表す固定 bit `1 << 22`.
        TARGET_PRACTICE (Mod): `TARGET_PRACTICE` を表す固定 bit `1 << 23`.
        KEY9 (Mod): `KEY9` を表す固定 bit `1 << 24`.
        KEY_COOP (Mod): `KEY_COOP` を表す固定 bit `1 << 25`.
        KEY1 (Mod): `KEY1` を表す固定 bit `1 << 26`.
        KEY3 (Mod): `KEY3` を表す固定 bit `1 << 27`.
        KEY2 (Mod): `KEY2` を表す固定 bit `1 << 28`.
        SCORE_V2 (Mod): `SCORE_V2` を表す固定 bit `1 << 29`.
        MIRROR (Mod): `MIRROR` を表す固定 bit `1 << 30`.

    Notes:
        各値はこの domain で固定の bit 位置を持つ. stable client 固有の bitmask mapping は
        この enum の責務ではない.
    """

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
    """canonical mod の不変な組み合わせを表す値オブジェクト.

    Attributes:
        mods (Mod): 適用された mod flag の bitwise 組み合わせ. 既知外の非負 bit も保持できる.
    """

    mods: Mod = Mod.NONE

    @classmethod
    def none(cls) -> Self:
        """Mod を適用しない組み合わせを返す.

        Returns:
            Self: `Mod.NONE` だけを保持する新しい組み合わせ.
        """
        return cls(Mod.NONE)

    @classmethod
    def from_bitmask(cls, bitmask: int) -> Self:
        """非負の canonical bitmask から mod 組み合わせを作成する.

        Args:
            bitmask (int): protocol または内部処理から得た非負の mod bitmask.

        Returns:
            Self: 指定 bit を保持する mod 組み合わせ.

        Raises:
            ValueError: bitmask が負の場合.

        Notes:
            stable client 固有の bitmask 変換はここで行わない. `IntFlag` が保持できる
            未知 bit は切り捨てない.
        """
        if bitmask < 0:
            msg = "mod bitmask must be non-negative"
            raise ValueError(msg)
        return cls(Mod(bitmask))

    @classmethod
    def from_persistence_bitmask(cls, bitmask: int) -> Self:
        """永続化された canonical bitmask から mod 組み合わせを復元する.

        Args:
            bitmask (int): persistence から読み出した非負の canonical bitmask.

        Returns:
            Self: 指定 bit を保持する mod 組み合わせ.

        Raises:
            ValueError: bitmask が負の場合.
        """
        return cls.from_bitmask(bitmask)

    def has(self, mod: Mod) -> bool:
        """指定した mod flag 群がすべて含まれるか判定する.

        Args:
            mod (Mod): 含有を確認する一つ以上の mod flag.

        Returns:
            bool: `mod` の全 bit がこの組み合わせに含まれる場合は True.

        Notes:
            `Mod.NONE` は空集合なので常に含まれると判定する.
        """
        return (self.mods & mod) == mod

    def to_persistence_bitmask(self) -> int:
        """永続化できる canonical bitmask を返す.

        Returns:
            int: `mods` が保持する bitwise 値.
        """
        return int(self.mods)

    def unsupported_bits(self, supported_mods: Mod) -> int:
        """指定した対応 mod 集合に含まれない bit を返す.

        Args:
            supported_mods (Mod): 呼び出し側が対応すると宣言した mod flag の組み合わせ.

        Returns:
            int: この組み合わせにだけ含まれる未対応 bit の bitmask.
        """
        return self.to_persistence_bitmask() & ~int(supported_mods)

    def __contains__(self, mod: Mod) -> bool:
        """`in` 演算子で mod flag 群の含有を判定する.

        Args:
            mod (Mod): 含有を確認する mod flag.

        Returns:
            bool: `has()` と同じ全 bit 含有判定の結果.
        """
        return self.has(mod)

    def __int__(self) -> int:
        """組み合わせを canonical persistence bitmask へ変換する.

        Returns:
            int: `to_persistence_bitmask()` と同じ bitwise 値.
        """
        return self.to_persistence_bitmask()


__all__ = ["Mod", "ModCombination"]
