"""Unit tests for stable-facing performance response query."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, final

from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculation,
    PerformanceCalculationState,
)
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceCandidateSelection,
    ScorePerformanceRecalculationCandidateResult,
)
from osu_server.services.queries.scores.performance import (
    PerformanceResponseQuery,
    PerformanceSubmitResponseQuery,
    PerformanceSubmitResponseState,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
        PerformanceCompletionSignalPayload,
    )

_NOW = datetime(2026, 6, 16, tzinfo=UTC)


@dataclass(slots=True)
class _WaitCall:
    score_id: int
    timeout: timedelta


@final
class ScorePerformanceQueryRepositoryStub:
    """Typed score performance query repository test double."""

    def __init__(
        self,
        reads: tuple[PerformanceCalculation | None, ...],
    ) -> None:
        self._reads: list[PerformanceCalculation | None] = list(reads)
        self.score_ids: list[int] = []

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        self.score_ids.append(score_id)
        if len(self._reads) > 1:
            return self._reads.pop(0)
        return self._reads[0]

    async def select_recalculation_candidates(
        self,
        selection: ScorePerformanceCandidateSelection,
    ) -> ScorePerformanceRecalculationCandidateResult:
        _ = selection
        return ScorePerformanceRecalculationCandidateResult(
            candidates=(),
            reason_counts={},
        )


@final
class CompletionSignalStub:
    """Typed completion signal test double."""

    def __init__(
        self,
        *,
        observed: bool,
        on_wait: Callable[[], None] | None = None,
    ) -> None:
        self._observed: bool = observed
        self._on_wait: Callable[[], None] | None = on_wait
        self.waits: list[_WaitCall] = []

    async def notify(self, payload: PerformanceCompletionSignalPayload) -> None:
        _ = payload

    async def wait(self, score_id: int, timeout: timedelta) -> bool:
        self.waits.append(_WaitCall(score_id=score_id, timeout=timeout))
        if self._on_wait is not None:
            self._on_wait()
        return self._observed


async def test_completed_current_response_returns_stable_safe_integer_without_wait() -> None:
    """Completed current PP is rounded for stable response without waiting."""
    repository = ScorePerformanceQueryRepositoryStub(
        (_calculation(state=PerformanceCalculationState.COMPLETED, pp=Decimal("122.5")),)
    )
    signal = CompletionSignalStub(observed=False)

    result = await PerformanceResponseQuery(
        repository=repository,
        completion_signal=signal,
        bounded_wait=timedelta(seconds=5),
    ).wait_for_submit_response(PerformanceSubmitResponseQuery(score_id=42))

    assert result.state is PerformanceSubmitResponseState.COMPLETED
    assert result.stable_pp == 123
    assert result.retryable is False
    assert signal.waits == []


async def test_signal_observed_rereads_current_state_before_returning_pp() -> None:
    """Signal is only a wake-up hint; current DB state is re-read for PP."""
    repository = ScorePerformanceQueryRepositoryStub(
        (
            _calculation(state=PerformanceCalculationState.QUEUED),
            _calculation(state=PerformanceCalculationState.COMPLETED, pp=Decimal("98.49")),
        )
    )
    signal = CompletionSignalStub(observed=True)

    result = await PerformanceResponseQuery(
        repository=repository,
        completion_signal=signal,
        bounded_wait=timedelta(milliseconds=50),
    ).wait_for_submit_response(PerformanceSubmitResponseQuery(score_id=42))

    assert repository.score_ids == [42, 42]
    assert signal.waits == [_WaitCall(score_id=42, timeout=timedelta(milliseconds=50))]
    assert result.state is PerformanceSubmitResponseState.COMPLETED
    assert result.stable_pp == 98


async def test_timeout_performs_final_current_state_check_and_returns_completed() -> None:
    """Lost signal still converges on completed response when DB state changed."""
    repository = ScorePerformanceQueryRepositoryStub(
        (
            _calculation(state=PerformanceCalculationState.CALCULATING),
            _calculation(state=PerformanceCalculationState.COMPLETED, pp=Decimal("321.6")),
        )
    )
    signal = CompletionSignalStub(observed=False)

    result = await PerformanceResponseQuery(
        repository=repository,
        completion_signal=signal,
        bounded_wait=timedelta(milliseconds=50),
    ).wait_for_submit_response(PerformanceSubmitResponseQuery(score_id=42))

    assert repository.score_ids == [42, 42]
    assert result.state is PerformanceSubmitResponseState.COMPLETED
    assert result.stable_pp == 322
    assert result.retryable is False


async def test_timeout_final_check_returns_retryable_when_current_is_still_pending() -> None:
    """Pending current state after timeout is retryable."""
    repository = ScorePerformanceQueryRepositoryStub(
        (
            _calculation(state=PerformanceCalculationState.FETCHING_FILE),
            _calculation(state=PerformanceCalculationState.FETCHING_FILE),
        )
    )
    signal = CompletionSignalStub(observed=False)

    result = await PerformanceResponseQuery(
        repository=repository,
        completion_signal=signal,
        bounded_wait=timedelta(milliseconds=50),
    ).wait_for_submit_response(PerformanceSubmitResponseQuery(score_id=42))

    assert result.state is PerformanceSubmitResponseState.RETRYABLE
    assert result.stable_pp is None
    assert result.retryable is True


async def test_unavailable_current_response_is_accepted_with_zero_pp_without_diagnostics() -> None:
    """Unavailable current state is accepted as pp zero without exposing the reason."""
    repository = ScorePerformanceQueryRepositoryStub(
        (_calculation(state=PerformanceCalculationState.UNAVAILABLE),)
    )
    signal = CompletionSignalStub(observed=False)

    result = await PerformanceResponseQuery(
        repository=repository,
        completion_signal=signal,
        bounded_wait=timedelta(seconds=5),
    ).wait_for_submit_response(PerformanceSubmitResponseQuery(score_id=42))

    assert result.state is PerformanceSubmitResponseState.ACCEPTED_WITHOUT_PP
    assert result.stable_pp == 0
    assert result.retryable is False
    assert not hasattr(result, "unavailable_reason")
    assert signal.waits == []


async def test_out_of_scope_response_is_accepted_with_zero_pp_without_waiting() -> None:
    """Missing current calculation represents out-of-scope accepted pp zero."""
    repository = ScorePerformanceQueryRepositoryStub((None,))
    signal = CompletionSignalStub(observed=False)

    result = await PerformanceResponseQuery(
        repository=repository,
        completion_signal=signal,
        bounded_wait=timedelta(seconds=5),
    ).wait_for_submit_response(PerformanceSubmitResponseQuery(score_id=42))

    assert result.state is PerformanceSubmitResponseState.ACCEPTED_WITHOUT_PP
    assert result.stable_pp == 0
    assert result.retryable is False
    assert signal.waits == []


def _calculation(
    *,
    state: PerformanceCalculationState,
    pp: Decimal | None = None,
) -> PerformanceCalculation:
    return PerformanceCalculation(
        id=10,
        score_id=42,
        state=state,
        is_current=True,
        pp=pp,
        star_rating=Decimal("5.43") if state is PerformanceCalculationState.COMPLETED else None,
        calculator_name="rosu-pp-py",
        calculator_version="4.0.2",
        formula_profile=FormulaProfile.VANILLA_RANKED,
        beatmap_file_attachment_id=123 if state is PerformanceCalculationState.COMPLETED else None,
        beatmap_file_checksum_md5="a" * 32
        if state is PerformanceCalculationState.COMPLETED
        else None,
        unavailable_reason="osu_file_unusable"
        if state is PerformanceCalculationState.UNAVAILABLE
        else None,
        calculated_at=_NOW if state.is_terminal else None,
    )
