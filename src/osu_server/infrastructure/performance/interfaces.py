"""Performance calculator infrastructure contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Score


class PerformanceCalculatorStatus(Enum):
    """Terminal result status for one calculator invocation."""

    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"


class PerformanceCalculatorUnavailableReason(Enum):
    """Typed durable reasons for calculator-unavailable outcomes."""

    BEATMAP_PARSE_FAILED = "calculator_beatmap_parse_failed"
    BEATMAP_CONVERT_FAILED = "calculator_beatmap_convert_failed"
    BEATMAP_SUSPICIOUS = "calculator_beatmap_suspicious"
    CALCULATOR_INPUT_INVALID = "calculator_input_invalid"
    CALCULATOR_EXECUTION_FAILED = "calculator_execution_failed"


@dataclass(frozen=True, slots=True)
class PerformanceCalculatorInput:
    """Calculator input owned by Athena, without replay bytes."""

    score: Score
    osu_file_bytes: bytes


@dataclass(frozen=True, slots=True)
class PerformanceCalculatorCompleted:
    """PP and star rating output from the approved calculator."""

    pp: Decimal
    star_rating: Decimal
    status: PerformanceCalculatorStatus = field(
        init=False,
        default=PerformanceCalculatorStatus.COMPLETED,
    )

    def __post_init__(self) -> None:
        if self.pp < Decimal("0"):
            msg = "pp must be non-negative"
            raise ValueError(msg)
        if self.star_rating < Decimal("0"):
            msg = "star_rating must be non-negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PerformanceCalculatorUnavailable:
    """Durable unavailable outcome from calculator input or execution failure."""

    reason: PerformanceCalculatorUnavailableReason
    status: PerformanceCalculatorStatus = field(
        init=False,
        default=PerformanceCalculatorStatus.UNAVAILABLE,
    )


PerformanceCalculatorResult = PerformanceCalculatorCompleted | PerformanceCalculatorUnavailable


@runtime_checkable
class PerformanceCalculator(Protocol):
    """Boundary for PP and star rating calculation."""

    def calculator_name(self) -> str:
        """Return the stable calculator identity stored as provenance."""
        ...

    def calculator_version(self) -> str:
        """Return the installed calculator package version."""
        ...

    def calculate(self, input_data: PerformanceCalculatorInput) -> PerformanceCalculatorResult:
        """Calculate PP and stars or return a typed unavailable reason."""
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
