"""rosu-pp-py backed score performance calculator."""

from __future__ import annotations

from decimal import Decimal
from importlib import metadata
from typing import final

import rosu_pp_py as rosu

from osu_server.domain.scores.score import Ruleset
from osu_server.infrastructure.performance.interfaces import (
    PerformanceCalculatorCompleted,
    PerformanceCalculatorInput,
    PerformanceCalculatorResult,
    PerformanceCalculatorUnavailable,
    PerformanceCalculatorUnavailableReason,
)

_PACKAGE_NAME = "rosu-pp-py"
_CALCULATOR_NAME = "rosu-pp-py"
_MAX_ACCURACY_PERCENT = 100.0
_ROSU_MODE_BY_RULESET = {
    Ruleset.OSU: rosu.GameMode.Osu,
    Ruleset.TAIKO: rosu.GameMode.Taiko,
    Ruleset.CATCH: rosu.GameMode.Catch,
    Ruleset.MANIA: rosu.GameMode.Mania,
}


@final
class RosuPerformanceCalculator:
    """Calculate PP and star rating with rosu-pp-py."""

    def __init__(self) -> None:
        self._calculator_version = metadata.version(_PACKAGE_NAME)

    def calculator_name(self) -> str:
        return _CALCULATOR_NAME

    def calculator_version(self) -> str:
        return self._calculator_version

    def calculate(self, input_data: PerformanceCalculatorInput) -> PerformanceCalculatorResult:
        invalid_input = _validate_score_input(input_data)
        if invalid_input is not None:
            return invalid_input

        beatmap = _parse_beatmap(input_data.osu_file_bytes)
        if isinstance(beatmap, PerformanceCalculatorUnavailable):
            return beatmap

        if beatmap.n_objects <= 0:
            return PerformanceCalculatorUnavailable(
                PerformanceCalculatorUnavailableReason.BEATMAP_PARSE_FAILED
            )

        converted = _convert_beatmap(beatmap, input_data)
        if isinstance(converted, PerformanceCalculatorUnavailable):
            return converted

        if beatmap.is_suspicious():
            return PerformanceCalculatorUnavailable(
                PerformanceCalculatorUnavailableReason.BEATMAP_SUSPICIOUS
            )

        return _calculate_performance(beatmap, input_data)


def _validate_score_input(
    input_data: PerformanceCalculatorInput,
) -> PerformanceCalculatorUnavailable | None:
    score = input_data.score
    accuracy_percent = _accuracy_percent(input_data)
    if accuracy_percent < 0.0 or accuracy_percent > _MAX_ACCURACY_PERCENT:
        return PerformanceCalculatorUnavailable(
            PerformanceCalculatorUnavailableReason.CALCULATOR_INPUT_INVALID
        )
    if score.max_combo < 0 or score.score < 0:
        return PerformanceCalculatorUnavailable(
            PerformanceCalculatorUnavailableReason.CALCULATOR_INPUT_INVALID
        )
    if min(score.geki, score.katu, score.n300, score.n100, score.n50, score.miss) < 0:
        return PerformanceCalculatorUnavailable(
            PerformanceCalculatorUnavailableReason.CALCULATOR_INPUT_INVALID
        )
    return None


def _parse_beatmap(
    osu_file_bytes: bytes,
) -> rosu.Beatmap | PerformanceCalculatorUnavailable:
    try:
        return rosu.Beatmap(content=osu_file_bytes)
    except rosu.ParseError:
        return PerformanceCalculatorUnavailable(
            PerformanceCalculatorUnavailableReason.BEATMAP_PARSE_FAILED
        )
    except Exception:
        return PerformanceCalculatorUnavailable(
            PerformanceCalculatorUnavailableReason.CALCULATOR_EXECUTION_FAILED
        )


def _convert_beatmap(
    beatmap: rosu.Beatmap,
    input_data: PerformanceCalculatorInput,
) -> None | PerformanceCalculatorUnavailable:
    target_mode = _ROSU_MODE_BY_RULESET[input_data.score.ruleset]
    if beatmap.mode is target_mode:
        return None

    try:
        beatmap.convert(target_mode, _mods(input_data))
    except (rosu.ArgsError, rosu.ConvertError):
        return PerformanceCalculatorUnavailable(
            PerformanceCalculatorUnavailableReason.BEATMAP_CONVERT_FAILED
        )
    except Exception:
        return PerformanceCalculatorUnavailable(
            PerformanceCalculatorUnavailableReason.CALCULATOR_EXECUTION_FAILED
        )
    return None


def _calculate_performance(
    beatmap: rosu.Beatmap,
    input_data: PerformanceCalculatorInput,
) -> PerformanceCalculatorResult:
    try:
        attributes = rosu.Performance(
            mods=_mods(input_data),
            lazer=False,
            accuracy=_accuracy_percent(input_data),
            combo=input_data.score.max_combo,
            n_geki=input_data.score.geki,
            n_katu=input_data.score.katu,
            n300=input_data.score.n300,
            n100=input_data.score.n100,
            n50=input_data.score.n50,
            misses=input_data.score.miss,
            legacy_total_score=input_data.score.score,
        ).calculate(beatmap)
    except rosu.ArgsError:
        return PerformanceCalculatorUnavailable(
            PerformanceCalculatorUnavailableReason.CALCULATOR_INPUT_INVALID
        )
    except Exception:
        return PerformanceCalculatorUnavailable(
            PerformanceCalculatorUnavailableReason.CALCULATOR_EXECUTION_FAILED
        )

    return PerformanceCalculatorCompleted(
        pp=Decimal(str(attributes.pp)),
        star_rating=Decimal(str(attributes.difficulty.stars)),
    )


def _mods(input_data: PerformanceCalculatorInput) -> int:
    return input_data.score.mods.to_persistence_bitmask()


def _accuracy_percent(input_data: PerformanceCalculatorInput) -> float:
    accuracy = input_data.score.accuracy
    if 0.0 <= accuracy <= 1.0:
        return accuracy * 100.0
    return accuracy


__all__ = ("RosuPerformanceCalculator",)
