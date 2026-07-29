"""performance calculator infrastructure の契約値と port を定義します."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Score


class PerformanceCalculatorStatus(Enum):
    """一回の calculator 呼び出しに対する終端結果の状態です.

    Attributes:
        COMPLETED (PerformanceCalculatorStatus): 計算値を正常に取得した状態です.
        UNAVAILABLE (PerformanceCalculatorStatus): 計算不能理由を返した状態です.
    """

    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"


class PerformanceCalculatorUnavailableReason(Enum):
    """Calculator が利用不能になった結果を表す型付きで永続化可能な理由です.

    Attributes:
        BEATMAP_PARSE_FAILED (PerformanceCalculatorUnavailableReason): beatmap bytes を
            解析できません.
        BEATMAP_CONVERT_FAILED (PerformanceCalculatorUnavailableReason): ruleset へ変換できません.
        BEATMAP_SUSPICIOUS (PerformanceCalculatorUnavailableReason): suspicious beatmap と
            判定しました.
        CALCULATOR_INPUT_INVALID (PerformanceCalculatorUnavailableReason): score input が不正です.
        CALCULATOR_EXECUTION_FAILED (PerformanceCalculatorUnavailableReason): calculator 実行に
            失敗しました.
    """

    BEATMAP_PARSE_FAILED = "calculator_beatmap_parse_failed"
    BEATMAP_CONVERT_FAILED = "calculator_beatmap_convert_failed"
    BEATMAP_SUSPICIOUS = "calculator_beatmap_suspicious"
    CALCULATOR_INPUT_INVALID = "calculator_input_invalid"
    CALCULATOR_EXECUTION_FAILED = "calculator_execution_failed"


@dataclass(frozen=True, slots=True)
class PerformanceCalculatorInput:
    """Athena 所有で replay bytes を含まない calculator input です.

    Attributes:
        score (Score): performance を計算する score 値です.
        osu_file_bytes (bytes): score に対応する .osu beatmap の byte 列です.
    """

    score: Score
    osu_file_bytes: bytes


@dataclass(frozen=True, slots=True)
class PerformanceCalculatorCompleted:
    """承認済み calculator が返す PP と star rating の結果です.

    Attributes:
        pp (Decimal): 計算済みの performance point です.
        star_rating (Decimal): 計算済みの beatmap 難易度です.
        status (PerformanceCalculatorStatus): 常に COMPLETED となる終端状態です.
    """

    pp: Decimal
    star_rating: Decimal
    status: PerformanceCalculatorStatus = field(
        init=False,
        default=PerformanceCalculatorStatus.COMPLETED,
    )

    def __post_init__(self) -> None:
        """PP と star rating が非負であることを検証します.

        Returns:
            None: 値が有効であることを表します.

        Raises:
            ValueError: pp または star_rating が負の場合.
        """
        if self.pp < Decimal("0"):
            msg = "pp must be non-negative"
            raise ValueError(msg)
        if self.star_rating < Decimal("0"):
            msg = "star_rating must be non-negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PerformanceCalculatorUnavailable:
    """Calculator input または実行失敗による永続化可能な利用不能結果です.

    Attributes:
        reason (PerformanceCalculatorUnavailableReason): 計算不能になった分類済みの理由です.
        status (PerformanceCalculatorStatus): 常に UNAVAILABLE となる終端状態です.
    """

    reason: PerformanceCalculatorUnavailableReason
    status: PerformanceCalculatorStatus = field(
        init=False,
        default=PerformanceCalculatorStatus.UNAVAILABLE,
    )


PerformanceCalculatorResult = PerformanceCalculatorCompleted | PerformanceCalculatorUnavailable


@runtime_checkable
class PerformanceCalculator(Protocol):
    """PP と star rating を計算する infrastructure 境界です."""

    def calculator_name(self) -> str:
        """Calculator provenance として保存する安定した identity を返します.

        Returns:
            str: 実装を識別する安定した calculator 名です.
        """
        ...

    def calculator_version(self) -> str:
        """Calculator package の installed version を返します.

        Returns:
            str: 実装が使用する calculator package の version です.
        """
        ...

    def calculate(self, input_data: PerformanceCalculatorInput) -> PerformanceCalculatorResult:
        """PP と star rating を計算し,不能時は型付き理由を返します.

        Args:
            input_data (PerformanceCalculatorInput): score と .osu bytes を含む計算入力です.

        Returns:
            PerformanceCalculatorResult: 計算済み値または利用不能理由を持つ終端結果です.
        """
        ...


__all__ = (
    "PerformanceCalculator",
    "PerformanceCalculatorCompleted",
    "PerformanceCalculatorInput",
    "PerformanceCalculatorResult",
    "PerformanceCalculatorStatus",
    "PerformanceCalculatorUnavailable",
    "PerformanceCalculatorUnavailableReason",
)
