"""Canonical score mod domain tests."""

from __future__ import annotations

from datetime import UTC, datetime
from inspect import get_annotations
from typing import get_type_hints

from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.payload_parser import ParsedScore
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score


def test_mod_combination_preserves_bitmask_for_persistence() -> None:
    combination = ModCombination.from_bitmask(72)

    assert combination.has(Mod.HIDDEN)
    assert combination.has(Mod.DOUBLE_TIME)
    assert not combination.has(Mod.HARD_ROCK)
    assert combination.to_persistence_bitmask() == 72


def test_score_and_parsed_score_use_canonical_mod_combination() -> None:
    parsed_hints = get_type_hints(ParsedScore, globalns={"ModCombination": ModCombination})

    assert get_annotations(Score)["mods"] == "ModCombination"
    assert parsed_hints["mods"] is ModCombination


def test_mod_combination_does_not_own_stable_bitmask_mapping() -> None:
    assert not hasattr(ModCombination, "from_stable_bitmask")


def test_score_keeps_canonical_mods_while_storage_can_use_integer_bitmask() -> None:
    mods = ModCombination.from_bitmask(88)
    score = Score(
        id=None,
        user_id=1,
        beatmap_id=2,
        beatmap_checksum="beatmap",
        online_checksum="online",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=mods,
        n300=300,
        n100=10,
        n50=2,
        geki=0,
        katu=0,
        miss=1,
        score=123456,
        max_combo=500,
        accuracy=98.5,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="20240101",
        submitted_at=datetime(2024, 1, 1, tzinfo=UTC),
    )

    assert score.mods == mods
    assert score.mods.to_persistence_bitmask() == 88
