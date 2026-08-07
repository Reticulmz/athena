"""rosu-pp-py を用いて score の performance を計算します."""

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
    """rosu-pp-py で PP と star rating を計算します.

    Attributes:
        _calculator_version (str): 初期化時に固定する rosu-pp-py package の version です.
    """

    def __init__(self) -> None:
        """Rosu-pp-py package の installed version を初期化します.

        Raises:
            metadata.PackageNotFoundError: rosu-pp-py package を発見できない場合.
        """
        self._calculator_version = metadata.version(_PACKAGE_NAME)

    def calculator_name(self) -> str:
        """Calculator provenance に保存する安定した calculator 名を返します.

        Returns:
            str: rosu-pp-py を表す安定した calculator 名です.
        """
        return _CALCULATOR_NAME

    def calculator_version(self) -> str:
        """初期化時に読み取った rosu-pp-py package version を返します.

        Returns:
            str: installed rosu-pp-py package の version です.
        """
        return self._calculator_version

    def calculate(self, input_data: PerformanceCalculatorInput) -> PerformanceCalculatorResult:
        """入力 score と .osu bytes から PP と star rating を計算します.

        Args:
            input_data (PerformanceCalculatorInput): score と対応する .osu bytes を持つ
                計算入力です.

        Returns:
            PerformanceCalculatorResult: 計算済み値,または解析,変換,入力,実行失敗を表す
                型付き利用不能結果です.

        Notes:
            rosu-pp-py が処理できない input は例外として伝播せず,利用不能結果へ変換します.
        """
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
    """入力 score が calculator の数値範囲を満たすか確認します.

    Args:
        input_data (PerformanceCalculatorInput): 検証する score と .osu bytes の入力です.

    Returns:
        PerformanceCalculatorUnavailable | None: 不正な場合は利用不能結果,有効な場合は None です.
    """
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
    """.osu byte 列を rosu beatmap へ解析します.

    Args:
        osu_file_bytes (bytes): 解析する .osu beatmap の byte 列です.

    Returns:
        rosu.Beatmap | PerformanceCalculatorUnavailable: 解析済み beatmap,または解析・実行失敗を
            表す利用不能結果です.

    Notes:
        rosu.ParseError と予期しない実行例外は利用不能結果へ変換します.
    """
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
    """対象 beatmap を score の ruleset に必要な場合だけ変換します.

    Args:
        beatmap (rosu.Beatmap): 解析済みで変換対象となる beatmap です.
        input_data (PerformanceCalculatorInput): 変換先 ruleset と mod を持つ計算入力です.

    Returns:
        None | PerformanceCalculatorUnavailable: 変換不要または成功時は None,変換・実行失敗時は
            利用不能結果です.

    Notes:
        rosu.ArgsError,rosu.ConvertError,予期しない実行例外は利用不能結果へ変換します.
    """
    target_mode = _ROSU_MODE_BY_RULESET[input_data.score.ruleset]
    if beatmap.mode is target_mode:
        return None

    try:
        beatmap.convert(target_mode, _mods(input_data))
    except rosu.ArgsError, rosu.ConvertError:
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
    """変換済み beatmap と score input から performance 値を計算します.

    Args:
        beatmap (rosu.Beatmap): 計算対象として解析・変換済みの beatmap です.
        input_data (PerformanceCalculatorInput): mod,accuracy,hit count を持つ計算入力です.

    Returns:
        PerformanceCalculatorResult: PP と star rating の結果,または入力・実行失敗を表す
            利用不能結果です.

    Notes:
        rosu.ArgsError と予期しない実行例外は利用不能結果へ変換します.
    """
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
    """入力 score の canonical mod 値を persistence bitmask へ変換します.

    Args:
        input_data (PerformanceCalculatorInput): 変換する mod 値を含む計算入力です.

    Returns:
        int: rosu-pp-py へ渡す persistence bitmask です.
    """
    return input_data.score.mods.to_persistence_bitmask()


def _accuracy_percent(input_data: PerformanceCalculatorInput) -> float:
    """入力 score の accuracy を rosu-pp-py 用 percent 表現へ正規化します.

    Args:
        input_data (PerformanceCalculatorInput): ratio または percent の accuracy を持つ
            計算入力です.

    Returns:
        float: 0.0 から 100.0 の percent 表現,または入力された percent 表現です.

    Notes:
        0.0 から 1.0 の値だけを ratio とみなし 100 倍します.
    """
    accuracy = input_data.score.accuracy
    if 0.0 <= accuracy <= 1.0:
        return accuracy * 100.0
    return accuracy


__all__ = ("RosuPerformanceCalculator",)
