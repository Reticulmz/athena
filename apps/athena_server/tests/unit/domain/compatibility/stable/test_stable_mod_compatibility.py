"""Stable mod compatibility mappingの境界契約を検証する."""

from __future__ import annotations

import pytest

from osu_server.domain.compatibility.stable.mods import (
    StableModMappingStatus,
    mod_combination_to_stable_bitmask,
    stable_mod_bitmask_to_mod_combination,
)
from osu_server.domain.scores.mods import Mod, ModCombination


def test_stable_bitmask_canonicalizes_to_mod_combination() -> None:
    """Stable bitmaskをcanonical ModCombinationへ同じbit集合として変換することを検証する.

    Returns:
        None: HIDDENとDOUBLE_TIMEを含む変換結果を検証して完了する.

    Raises:
        AssertionError: Stable inputのcanonical化でbit集合が変化した場合.
    """
    combination = stable_mod_bitmask_to_mod_combination(72)

    assert combination == ModCombination.from_bitmask(72)
    assert combination.has(Mod.HIDDEN)
    assert combination.has(Mod.DOUBLE_TIME)


def test_supported_canonical_mod_combination_maps_back_to_stable_bitmask() -> None:
    """Stable対応canonical mod群を完全なbitmaskとして逆変換できることを検証する.

    Returns:
        None: SUPPORTED status, 元のbitmask, 未対応bitなしを検証して完了する.

    Raises:
        AssertionError: 対応可能なcanonical modがStable表現へ完全変換できない場合.
    """
    result = mod_combination_to_stable_bitmask(
        ModCombination.from_bitmask(72),
    )

    assert result.status == StableModMappingStatus.SUPPORTED
    assert result.bitmask == 72
    assert result.unsupported_bits == 0


def test_unsupported_canonical_mod_bits_are_explicit_at_stable_boundary() -> None:
    """Stable非対応canonical bitをUNSUPPORTED outcomeとして明示することを検証する.

    Returns:
        None: bitmaskを返さず未対応bitを保持するoutcomeを検証して完了する.

    Raises:
        AssertionError: Stable境界が未対応bitを黙って変換または破棄した場合.
    """
    unsupported_lazer_bit = 1 << 31
    result = mod_combination_to_stable_bitmask(
        ModCombination.from_bitmask(unsupported_lazer_bit),
    )

    assert result.status == StableModMappingStatus.UNSUPPORTED
    assert result.bitmask is None
    assert result.unsupported_bits == unsupported_lazer_bit


def test_stable_input_rejects_unsupported_positive_bits() -> None:
    """Signed integer範囲外へ到達するStable未対応bitを拒否する.

    Returns:
        None: bit 31がValueErrorになることを検証して完了する.

    Raises:
        AssertionError: Stable未対応bitがModCombinationとして受理された場合.
    """
    with pytest.raises(ValueError, match="unsupported bits"):
        _ = stable_mod_bitmask_to_mod_combination(1 << 31)
