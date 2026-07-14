"""Stable mod compatibility mapping tests."""

from __future__ import annotations

import pytest

from osu_server.domain.compatibility.stable.mods import (
    StableModMappingStatus,
    mod_combination_to_stable_bitmask,
    stable_mod_bitmask_to_mod_combination,
)
from osu_server.domain.scores.mods import Mod, ModCombination


def test_stable_bitmask_canonicalizes_to_mod_combination() -> None:
    combination = stable_mod_bitmask_to_mod_combination(72)

    assert combination == ModCombination.from_bitmask(72)
    assert combination.has(Mod.HIDDEN)
    assert combination.has(Mod.DOUBLE_TIME)


def test_supported_canonical_mod_combination_maps_back_to_stable_bitmask() -> None:
    result = mod_combination_to_stable_bitmask(
        ModCombination.from_bitmask(72),
    )

    assert result.status == StableModMappingStatus.SUPPORTED
    assert result.bitmask == 72
    assert result.unsupported_bits == 0


def test_unsupported_canonical_mod_bits_are_explicit_at_stable_boundary() -> None:
    unsupported_lazer_bit = 1 << 31
    result = mod_combination_to_stable_bitmask(
        ModCombination.from_bitmask(unsupported_lazer_bit),
    )

    assert result.status == StableModMappingStatus.UNSUPPORTED
    assert result.bitmask is None
    assert result.unsupported_bits == unsupported_lazer_bit


def test_stable_input_rejects_unsupported_positive_bits() -> None:
    """signed Integer範囲外へ到達するstable未対応bitを拒否する.

    Returns:
        None: bit 31がValueErrorになることを示す.

    Raises:
        AssertionError: stable未対応bitがModCombinationとして受理された場合.
    """
    with pytest.raises(ValueError, match="unsupported bits"):
        _ = stable_mod_bitmask_to_mod_combination(1 << 31)
