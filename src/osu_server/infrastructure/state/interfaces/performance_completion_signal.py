"""Performance completion signal contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.scores.performance import PerformanceCalculationState


@dataclass(frozen=True, slots=True)
class PerformanceCompletionSignalPayload:
    """Wake-up payload for a terminal score performance calculation."""

    score_id: int
    calculation_id: int
    state: PerformanceCalculationState

    def __post_init__(self) -> None:
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)
        if self.calculation_id <= 0:
            msg = "calculation_id must be positive"
            raise ValueError(msg)
        if not self.state.is_terminal:
            msg = "performance completion signal state must be terminal"
            raise ValueError(msg)


@runtime_checkable
class PerformanceCompletionSignal(Protocol):
    """Best-effort score-scoped wake-up signal for performance completion."""

    async def notify(self, payload: PerformanceCompletionSignalPayload) -> None:
        """Publish a wake-up hint after a terminal calculation is committed."""
        ...

    async def wait(self, score_id: int, timeout: timedelta) -> bool:
        """Return True when a signal is observed, False when the wait times out."""
        ...


def performance_completion_channel(score_id: int, *, key_prefix: str = "") -> str:
    """Return the deterministic score-scoped completion channel."""
    if score_id <= 0:
        msg = "score_id must be positive"
        raise ValueError(msg)
    return f"{key_prefix}performance_completion:{score_id}"


def validate_performance_completion_timeout(timeout: timedelta) -> None:
    """Reject non-positive bounded wait values."""
    if timeout <= timedelta(0):
        msg = "timeout must be positive"
        raise ValueError(msg)
