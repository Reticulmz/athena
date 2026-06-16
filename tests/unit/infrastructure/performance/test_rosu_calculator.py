"""Tests for rosu-pp-py performance calculation adapter."""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from importlib import metadata
from pathlib import Path

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.infrastructure.performance.interfaces import (
    PerformanceCalculatorCompleted,
    PerformanceCalculatorInput,
    PerformanceCalculatorStatus,
    PerformanceCalculatorUnavailable,
    PerformanceCalculatorUnavailableReason,
)
from osu_server.infrastructure.performance.rosu_calculator import RosuPerformanceCalculator

_NOW = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)
_PROJECT_ROOT = Path(__file__).parents[4]
_ROSU_ADAPTER_PATH = Path("src/osu_server/infrastructure/performance/rosu_calculator.py")
_OSU_FILE = b"""osu file format v14

[General]
AudioFilename: audio.mp3
Mode: 0

[Metadata]
Title:Test
Artist:Test
Creator:Test
Version:Normal
BeatmapID:1
BeatmapSetID:1

[Difficulty]
HPDrainRate:5
CircleSize:4
OverallDifficulty:6
ApproachRate:7
SliderMultiplier:1.4
SliderTickRate:1

[TimingPoints]
0,500,4,2,1,50,1,0

[HitObjects]
256,192,1000,1,0,0:0:0:0:
128,192,1500,1,0,0:0:0:0:
384,192,2000,1,0,0:0:0:0:
"""


def test_calculator_uses_package_version_metadata() -> None:
    calculator = RosuPerformanceCalculator()

    assert calculator.calculator_name() == "rosu-pp-py"
    assert calculator.calculator_version() == metadata.version("rosu-pp-py")


def test_rosu_pp_py_import_stays_inside_adapter() -> None:
    importers = [
        path.relative_to(_PROJECT_ROOT)
        for path in (_PROJECT_ROOT / "src" / "osu_server").rglob("*.py")
        if _imports_rosu_pp_py(path)
    ]

    assert importers == [_ROSU_ADAPTER_PATH]


def test_calculator_returns_pp_and_stars_from_score_and_osu_bytes() -> None:
    calculator = RosuPerformanceCalculator()

    result = calculator.calculate(
        PerformanceCalculatorInput(score=_score(), osu_file_bytes=_OSU_FILE)
    )

    assert isinstance(result, PerformanceCalculatorCompleted)
    assert result.status is PerformanceCalculatorStatus.COMPLETED
    assert result.pp > Decimal("0")
    assert result.star_rating > Decimal("0")


def test_calculator_accepts_existing_percent_accuracy_for_legacy_rows() -> None:
    calculator = RosuPerformanceCalculator()
    ratio_score = _score(accuracy=1.0)
    percent_score = replace(ratio_score, accuracy=100.0)

    ratio_result = calculator.calculate(
        PerformanceCalculatorInput(score=ratio_score, osu_file_bytes=_OSU_FILE)
    )
    percent_result = calculator.calculate(
        PerformanceCalculatorInput(score=percent_score, osu_file_bytes=_OSU_FILE)
    )

    assert isinstance(ratio_result, PerformanceCalculatorCompleted)
    assert isinstance(percent_result, PerformanceCalculatorCompleted)
    assert percent_result.pp == ratio_result.pp
    assert percent_result.star_rating == ratio_result.star_rating


def test_calculator_does_not_require_replay_bytes() -> None:
    input_data = PerformanceCalculatorInput(score=_score(), osu_file_bytes=_OSU_FILE)

    assert not hasattr(input_data, "replay_bytes")
    assert isinstance(
        RosuPerformanceCalculator().calculate(input_data), PerformanceCalculatorCompleted
    )


def test_calculator_returns_unavailable_for_empty_or_unparseable_map() -> None:
    result = RosuPerformanceCalculator().calculate(
        PerformanceCalculatorInput(score=_score(), osu_file_bytes=b"not an osu file")
    )

    assert isinstance(result, PerformanceCalculatorUnavailable)
    assert result.status is PerformanceCalculatorStatus.UNAVAILABLE
    assert result.reason is PerformanceCalculatorUnavailableReason.BEATMAP_PARSE_FAILED


def test_calculator_returns_unavailable_for_invalid_score_input() -> None:
    result = RosuPerformanceCalculator().calculate(
        PerformanceCalculatorInput(
            score=replace(_score(), accuracy=-0.1),
            osu_file_bytes=_OSU_FILE,
        )
    )

    assert isinstance(result, PerformanceCalculatorUnavailable)
    assert result.reason is PerformanceCalculatorUnavailableReason.CALCULATOR_INPUT_INVALID


def _score(*, accuracy: float = 1.0) -> Score:
    return Score(
        id=1,
        user_id=100,
        beatmap_id=200,
        beatmap_checksum="a" * 32,
        online_checksum="b" * 32,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=3,
        n100=0,
        n50=0,
        geki=0,
        katu=0,
        miss=0,
        score=1_000_000,
        max_combo=3,
        accuracy=accuracy,
        grade=Grade.X,
        passed=True,
        perfect=True,
        client_version="b20250101",
        submitted_at=_NOW,
        beatmap_status_at_submission=BeatmapRankStatus.RANKED.value,
    )


def _imports_rosu_pp_py(path: Path) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "rosu_pp_py" or alias.name.startswith("rosu_pp_py."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "rosu_pp_py" or module.startswith("rosu_pp_py."):
                return True
    return False
