"""stable向けperformance response queryのunit testを定義する."""

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
    """completion signalのwait呼び出しを記録する.

    Attributes:
        score_id (int): wait対象のscore識別子.
        timeout (timedelta): queryがsignalを待機する上限時間.
    """

    score_id: int
    timeout: timedelta


@final
class ScorePerformanceQueryRepositoryStub:
    """score performance query repositoryのtyped test doubleを提供する.

    Attributes:
        _reads (list[PerformanceCalculation | None]): score readごとに返すcurrent calculation列.
        score_ids (list[int]): get_current_for_scoreへ渡されたscore識別子.
    """

    def __init__(
        self,
        reads: tuple[PerformanceCalculation | None, ...],
    ) -> None:
        """順に返すcurrent calculation列でrepository stubを初期化する.

        Args:
            reads (tuple[PerformanceCalculation | None, ...]): testが観測する各read結果.
                少なくとも1件を指定する.
        """
        self._reads: list[PerformanceCalculation | None] = list(reads)
        self.score_ids: list[int] = []

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        """scoreのcurrent calculationを順に返す.

        Args:
            score_id (int): current calculationを読むscoreの識別子.

        Returns:
            PerformanceCalculation | None: 未消費の先頭read結果. 最終結果は以後も繰り返して返す.
        """
        self.score_ids.append(score_id)
        if len(self._reads) > 1:
            return self._reads.pop(0)
        return self._reads[0]

    async def select_recalculation_candidates(
        self,
        selection: ScorePerformanceCandidateSelection,
    ) -> ScorePerformanceRecalculationCandidateResult:
        """recalculation候補を持たない空の選択結果を返す.

        Args:
            selection (ScorePerformanceCandidateSelection): 呼び出し側が指定する候補選択条件.

        Returns:
            ScorePerformanceRecalculationCandidateResult: 候補と理由別件数がともに空の結果.
        """
        _ = selection
        return ScorePerformanceRecalculationCandidateResult(
            candidates=(),
            reason_counts={},
        )


@final
class CompletionSignalStub:
    """performance completion signalのtyped test doubleを提供する.

    Attributes:
        _observed (bool): waitが観測済みとして返す値.
        _on_wait (Callable[[], None] | None): wait時にread結果を進める任意のcallback.
        waits (list[_WaitCall]): waitへ渡されたscore IDとtimeoutの記録.
    """

    def __init__(
        self,
        *,
        observed: bool,
        on_wait: Callable[[], None] | None = None,
    ) -> None:
        """wait結果と任意のwait callbackでsignal stubを初期化する.

        Args:
            observed (bool): waitがcompletion signalを観測したとして返す値.
            on_wait (Callable[[], None] | None): waitの直前に実行するcallback.
                指定しない場合は状態を変更しない.
        """
        self._observed: bool = observed
        self._on_wait: Callable[[], None] | None = on_wait
        self.waits: list[_WaitCall] = []

    async def notify(self, payload: PerformanceCompletionSignalPayload) -> None:
        """通知payloadを無視して完了する.

        Args:
            payload (PerformanceCompletionSignalPayload): production interfaceと互換に受け取る
                completion通知.

        Returns:
            None: 通知を記録せず、呼び出し側へ値を返さずに完了する.
        """
        _ = payload

    async def wait(self, score_id: int, timeout: timedelta) -> bool:
        """wait呼び出しを記録して設定済みの観測結果を返す.

        Args:
            score_id (int): completionを待つscoreの識別子.
            timeout (timedelta): 呼び出し側が許容する待機時間.

        Returns:
            bool: 初期化時に指定されたsignal観測結果.
        """
        self.waits.append(_WaitCall(score_id=score_id, timeout=timeout))
        if self._on_wait is not None:
            self._on_wait()
        return self._observed


async def test_completed_current_response_returns_stable_safe_integer_without_wait() -> None:
    """完了済みPPが待機なしでstable用整数へ丸められる契約を検証する.

    completed calculationを初回readで返し、completion signalを待たずに四捨五入済みPPと
    non-retryable結果を返すことを確認する.

    Returns:
        None: stable responseの状態、PP、待機回数を検証して完了する.
    """
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
    """Completion signal後にcurrent stateを再readする契約を検証する.

    queued calculationの後にcompleted calculationを返し、signalをwake-up hintとして扱って
    最新stateから整数PPを返すことを確認する.

    Returns:
        None: repository read履歴、wait引数、completed responseを検証して完了する.
    """
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
    """timeout後の最終current state確認がcompleted結果へ収束することを検証する.

    signal未観測の待機後にrepositoryがcompleted calculationを返す条件で、最終readから
    completed responseを返すことを確認する.

    Returns:
        None: 最終read回数、丸め済みPP、non-retryable状態を検証して完了する.
    """
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
    """timeout後もpendingなcurrent stateがretryableになる契約を検証する.

    初回と最終readがともに非terminal stateの条件で、PPを返さずretryable responseを
    返すことを確認する.

    Returns:
        None: response state、PP、retryable flagを検証して完了する.
    """
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
    """Unavailable current stateがdiagnosticなしのPPゼロとして受理されることを検証する.

    unavailable calculationを返す条件で、内部reasonを公開せずaccepted-without-PP responseを
    返すことを確認する.

    Returns:
        None: response state、ゼロPP、非公開diagnostic、待機なしを検証して完了する.
    """
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
    """Current calculation不在が待機なしのPPゼロとして受理されることを検証する.

    repositoryがNoneを返す条件で、out-of-scopeとしてaccepted-without-PP responseを即時に
    返すことを確認する.

    Returns:
        None: response state、ゼロPP、非retryable状態、待機なしを検証して完了する.
    """
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
    """指定stateのperformance calculation fixtureを構築する.

    Args:
        state (PerformanceCalculationState): fixtureへ設定するcalculation lifecycle state.
        pp (Decimal | None): completed calculationへ設定するperformance point.
            指定しない場合はNone.

    Returns:
        PerformanceCalculation: stateに応じたterminal metadataとoptional PPを持つcalculation.
    """
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
