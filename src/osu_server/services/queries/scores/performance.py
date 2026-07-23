"""Stable score submit 向けの performance response query を提供する."""

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
    """Stable score submit 向け performance response の状態を表す.

    Attributes:
        COMPLETED (PerformanceSubmitResponseState): PP 計算済みの応答.
        RETRYABLE (PerformanceSubmitResponseState): PP 計算が継続中で再試行可能な応答.
        ACCEPTED_WITHOUT_PP (PerformanceSubmitResponseState): score を受理済みだが PP を
            まだ返せない応答.
    """

    COMPLETED = "completed"
    RETRYABLE = "retryable"
    ACCEPTED_WITHOUT_PP = "accepted_without_pp"


@dataclass(frozen=True, slots=True)
class PerformanceSubmitResponseQuery:
    """Score submit PP response を読むための query input を表す.

    Attributes:
        score_id (int): response を取得する受理済み score の ID.
    """

    score_id: int

    def __post_init__(self) -> None:
        """Score ID が正の値であることを検証する.

        Returns:
            None: 検証が完了したことを表す.

        Raises:
            ValueError: score_id がゼロ以下の場合.
        """
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PerformanceSubmitResponse:
    """受理済み score に対する Stable PP response を表す.

    Attributes:
        state (PerformanceSubmitResponseState): PP 計算の現在状態.
        stable_pp (int | None): Stable client に返す丸め済み PP. 再試行可能な場合は None.
    """

    state: PerformanceSubmitResponseState
    stable_pp: int | None

    @property
    def retryable(self) -> bool:
        """PP 計算の再試行が必要な状態かどうかを返す.

        Returns:
            bool: state が RETRYABLE の場合は True.
        """
        return self.state is PerformanceSubmitResponseState.RETRYABLE


@final
class PerformanceResponseQuery:
    """現在の performance state から Stable submit response を組み立てる.

    Attributes:
        _repository (ScorePerformanceQueryRepository): score ごとの performance state を読む
            query repository.
        _completion_signal (PerformanceCompletionSignal): performance 計算完了を待つ signal.
        _bounded_wait (timedelta): submit response の最大待機時間.
    """

    def __init__(
        self,
        *,
        repository: ScorePerformanceQueryRepository,
        completion_signal: PerformanceCompletionSignal,
        bounded_wait: timedelta,
    ) -> None:
        """Performance state の reader, completion signal, 待機上限を設定する.

        Args:
            repository (ScorePerformanceQueryRepository): score の performance state を読む
                repository.
            completion_signal (PerformanceCompletionSignal): 計算完了を待機する signal.
            bounded_wait (timedelta): pending state を待つ正の最大時間.

        Raises:
            ValueError: bounded_wait がゼロ以下の場合.
        """
        validate_performance_completion_timeout(bounded_wait)
        self._repository = repository
        self._completion_signal = completion_signal
        self._bounded_wait = bounded_wait

    async def wait_for_submit_response(
        self,
        query: PerformanceSubmitResponseQuery,
    ) -> PerformanceSubmitResponse:
        """Pending performance 計算を上限時間だけ待機して submit response を返す.

        Args:
            query (PerformanceSubmitResponseQuery): response を取得する score の query input.

        Returns:
            PerformanceSubmitResponse: 完了 PP, PP なしの受理結果, または再試行可能な結果.

        Raises:
            ValueError: 完了済み performance calculation に PP がない場合.
        """
        current = await self._repository.get_current_for_score(query.score_id)
        if current is None or not current.state.is_pending:
            return _response_from_current(current)

        _ = await self._completion_signal.wait(query.score_id, self._bounded_wait)
        current = await self._repository.get_current_for_score(query.score_id)
        return _response_from_current(current)

    async def get_submit_response(
        self,
        query: PerformanceSubmitResponseQuery,
    ) -> PerformanceSubmitResponse:
        """Pending work を待機せず現在の submit response を返す.

        Args:
            query (PerformanceSubmitResponseQuery): response を取得する score の query input.

        Returns:
            PerformanceSubmitResponse: 現在の PP response. pending state は PP なしの
                受理結果になる.

        Raises:
            ValueError: 完了済み performance calculation に PP がない場合.
        """
        current = await self._repository.get_current_for_score(query.score_id)
        if current is not None and current.state.is_pending:
            return _accepted_without_pp()
        return _response_from_current(current)


def _response_from_current(
    current: PerformanceCalculation | None,
) -> PerformanceSubmitResponse:
    """現在の performance calculation を Stable submit response へ変換する.

    Args:
        current (PerformanceCalculation | None): score に紐付く現在の calculation. 未作成時は
            None.

    Returns:
        PerformanceSubmitResponse: calculation state に対応する Stable submit response.

    Raises:
        ValueError: 完了済み calculation に PP がない場合.
    """
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
    """PP 未計算でも score が受理済みであることを表す response を作る.

    Returns:
        PerformanceSubmitResponse: stable_pp を 0 とする PP なしの受理結果.
    """
    return PerformanceSubmitResponse(
        state=PerformanceSubmitResponseState.ACCEPTED_WITHOUT_PP,
        stable_pp=0,
    )


def _stable_pp(calculation: PerformanceCalculation) -> int:
    """完了済み performance calculation の PP を Stable 整数値へ丸める.

    Args:
        calculation (PerformanceCalculation): PP を持つことが期待される完了済み calculation.

    Returns:
        int: ROUND_HALF_UP で丸めた Stable client 向け PP.

    Raises:
        ValueError: calculation.pp が None の場合.
    """
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
