"""Stable-facing score performance response query."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP
from enum import Enum
from typing import TYPE_CHECKING, final

from osu_server.domain.scores.performance import PerformanceCalculationState
from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
    validate_performance_completion_timeout,
)

if TYPE_CHECKING:
    from datetime import timedelta

    from osu_server.domain.scores.performance import PerformanceCalculation
    from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
        PerformanceCompletionSignal,
    )
    from osu_server.repositories.interfaces.queries.score_performance import (
        ScorePerformanceQueryRepository,
    )


class PerformanceSubmitResponseState(Enum):
    """Stable-facing performance response state."""

    COMPLETED = "completed"
    RETRYABLE = "retryable"
    ACCEPTED_WITHOUT_PP = "accepted_without_pp"


@dataclass(frozen=True, slots=True)
class PerformanceSubmitResponseQuery:
    """Query input for score submit PP response data."""

    score_id: int

    def __post_init__(self) -> None:
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PerformanceSubmitResponse:
    """Stable-facing PP response data for an accepted score."""

    state: PerformanceSubmitResponseState
    stable_pp: int | None

    @property
    def retryable(self) -> bool:
        return self.state is PerformanceSubmitResponseState.RETRYABLE


@final
class PerformanceResponseQuery:
    """Wait for current performance state and build stable response data."""

    def __init__(
        self,
        *,
        repository: ScorePerformanceQueryRepository,
        completion_signal: PerformanceCompletionSignal,
        bounded_wait: timedelta,
    ) -> None:
        validate_performance_completion_timeout(bounded_wait)
        self._repository = repository
        self._completion_signal = completion_signal
        self._bounded_wait = bounded_wait

    async def wait_for_submit_response(
        self,
        query: PerformanceSubmitResponseQuery,
    ) -> PerformanceSubmitResponse:
        """Return completed PP, accepted pp zero, or retryable pending state."""
        current = await self._repository.get_current_for_score(query.score_id)
        if current is None or not current.state.is_pending:
            return _response_from_current(current)

        _ = await self._completion_signal.wait(query.score_id, self._bounded_wait)
        current = await self._repository.get_current_for_score(query.score_id)
        return _response_from_current(current)


def _response_from_current(
    current: PerformanceCalculation | None,
) -> PerformanceSubmitResponse:
    if current is None:
        return _accepted_without_pp()
    if current.state is PerformanceCalculationState.COMPLETED:
        return PerformanceSubmitResponse(
            state=PerformanceSubmitResponseState.COMPLETED,
            stable_pp=_stable_pp(current),
        )
    if current.state is PerformanceCalculationState.UNAVAILABLE:
        return _accepted_without_pp()
    return PerformanceSubmitResponse(
        state=PerformanceSubmitResponseState.RETRYABLE,
        stable_pp=None,
    )


def _accepted_without_pp() -> PerformanceSubmitResponse:
    return PerformanceSubmitResponse(
        state=PerformanceSubmitResponseState.ACCEPTED_WITHOUT_PP,
        stable_pp=0,
    )


def _stable_pp(calculation: PerformanceCalculation) -> int:
    if calculation.pp is None:
        msg = "completed performance calculation requires pp"
        raise ValueError(msg)
    return int(calculation.pp.to_integral_value(rounding=ROUND_HALF_UP))


__all__ = (
    "PerformanceResponseQuery",
    "PerformanceSubmitResponse",
    "PerformanceSubmitResponseQuery",
    "PerformanceSubmitResponseState",
)
