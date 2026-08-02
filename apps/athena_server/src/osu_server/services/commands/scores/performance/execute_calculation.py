"""スコア performance calculation を実行する command use-case を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, final

from osu_server.domain.scores.performance import (
    PerformanceCalculationState,
    PerformanceEligibilityPolicy,
)
from osu_server.domain.scores.user_stats import UserStatsPolicy
from osu_server.infrastructure.performance import (
    PerformanceCalculatorCompleted,
    PerformanceCalculatorInput,
    PerformanceCalculatorUnavailable,
)
from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
    PerformanceCompletionSignalPayload,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    ClaimScorePerformanceCalculation,
    CompleteScorePerformanceCalculation,
    MarkScorePerformanceCalculationUnavailable,
    UpdateScorePerformanceCalculationState,
)
from osu_server.services.commands.scores.performance.beatmap_file_provider import (
    PerformanceBeatmapFilePending,
    PerformanceBeatmapFilePendingReason,
    PerformanceBeatmapFileQuery,
    PerformanceBeatmapFileReady,
    PerformanceBeatmapFileUnavailable,
)
from osu_server.services.commands.scores.performance.projection_refresh import (
    refresh_performance_best_for_current_score,
)
from osu_server.services.commands.scores.performance.runtime import (
    PerformanceRuntimeSettings,
)
from osu_server.services.commands.scores.user_stats_projection import (
    replace_current_user_stats_projection,
)

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.performance import PerformanceCalculation
    from osu_server.domain.scores.score import Score
    from osu_server.infrastructure.performance import PerformanceCalculator
    from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
        PerformanceCompletionSignal,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
    from osu_server.services.commands.scores.performance.beatmap_file_provider import (
        PerformanceBeatmapFileProvider,
    )


class ExecutePerformanceCalculationOutcome(Enum):
    """worker 側 performance calculation 実行の観測可能な結果を表す.

    Attributes:
        COMPLETED (ExecutePerformanceCalculationOutcome):
            calculation を完了し completion signal を処理した結果.
        UNAVAILABLE (ExecutePerformanceCalculationOutcome):
            入力または calculator の恒久的失敗を記録した結果.
        PENDING_INPUT (ExecutePerformanceCalculationOutcome):
            一時的に beatmap file 入力を待つ結果.
        CLAIM_NOT_ACQUIRED (ExecutePerformanceCalculationOutcome):
            calculation claim を取得できなかった結果.
        SCORE_NOT_FOUND (ExecutePerformanceCalculationOutcome):
            対象 score がなく unavailable 化した結果.
        FINALIZATION_CONFLICT (ExecutePerformanceCalculationOutcome):
            state 更新または terminal 化が競合した結果.
    """

    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    PENDING_INPUT = "pending_input"
    CLAIM_NOT_ACQUIRED = "claim_not_acquired"
    SCORE_NOT_FOUND = "score_not_found"
    FINALIZATION_CONFLICT = "finalization_conflict"


@dataclass(frozen=True, slots=True)
class ExecutePerformanceCalculationCommand:
    """1件の performance calculation を claim して実行する command を表す.

    Attributes:
        calculation_id (int): claim と terminal 化の対象となる正の calculation 識別子.
        claim_owner (str): work を所有する worker の空でない識別子.
        claimed_at (datetime): claim,state transition,calculation の基準時刻.
    """

    calculation_id: int
    claim_owner: str
    claimed_at: datetime

    def __post_init__(self) -> None:
        """対象 calculation id と claim owner の入力制約を検証する.

        Returns:
            None: command の不変条件を検証し,呼び出し側へ値を返さずに完了する.

        Raises:
            ValueError: calculation_id が0以下,または claim_owner が空文字列の場合.
        """
        if self.calculation_id <= 0:
            msg = "calculation_id must be positive"
            raise ValueError(msg)
        if self.claim_owner == "":
            msg = "claim_owner must not be empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ExecutePerformanceCalculationResult:
    """worker 側 performance calculation 実行の型付き結果を表す.

    Attributes:
        outcome (ExecutePerformanceCalculationOutcome): 実行,待機,競合の最終結果.
        calculation_id (int): command が対象にした calculation 識別子.
        score_id (int | None): 関連する score 識別子. claim 未取得時はNone.
        calculation (PerformanceCalculation | None):
            現在または terminal の calculation. ない場合はNone.
        pending_reason (PerformanceBeatmapFilePendingReason | None):
            再試行可能な file 入力待ち理由. ない場合はNone.
        unavailable_reason (str | None): unavailable 化した理由. 該当しない場合はNone.
        signal_notified (bool): terminal 結果の completion signal を通知できたか.
        signal_failed (bool): completion signal の通知で例外を捕捉したか.
        signal_error (str | None): 捕捉した signal 通知例外の文字列. 未発生時はNone.
    """

    outcome: ExecutePerformanceCalculationOutcome
    calculation_id: int
    score_id: int | None = None
    calculation: PerformanceCalculation | None = None
    pending_reason: PerformanceBeatmapFilePendingReason | None = None
    unavailable_reason: str | None = None
    signal_notified: bool = False
    signal_failed: bool = False
    signal_error: str | None = None


@dataclass(frozen=True, slots=True)
class _ClaimedCalculation:
    """claim を取得済みで score を解決済みの calculation 作業単位を表す.

    Attributes:
        calculation (PerformanceCalculation): claim 取得後に処理する calculation.
        score (Score): calculation に対応する永続 score.
    """

    calculation: PerformanceCalculation
    score: Score


@final
class ExecutePerformanceCalculationUseCase:
    """pending performance row を claim,計算,terminal 化,通知する."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        beatmap_file_provider: PerformanceBeatmapFileProvider,
        calculator: PerformanceCalculator,
        completion_signal: PerformanceCompletionSignal,
        settings: PerformanceRuntimeSettings | None = None,
        eligibility_policy: PerformanceEligibilityPolicy | None = None,
        user_stats_policy: UserStatsPolicy | None = None,
    ) -> None:
        """PP calculation の実行に必要な dependency を受け取る.

        Args:
            unit_of_work_factory (UnitOfWorkFactory):
                claim と terminal 化を行う command Unit of Work factory.
            beatmap_file_provider (PerformanceBeatmapFileProvider):
                calculation 用 osu file を解決する provider.
            calculator (PerformanceCalculator):
                score と osu file bytes から PP を計算する adapter.
            completion_signal (PerformanceCompletionSignal):
                terminal calculation を通知する境界.
            settings (PerformanceRuntimeSettings | None):
                claim timeout を含む実行時設定. 未指定時は既定値.
            eligibility_policy (PerformanceEligibilityPolicy | None):
                performance best 更新の eligibility policy. 未指定時は既定 policy.
            user_stats_policy (UserStatsPolicy | None):
                user stats projection 更新の policy. 未指定時は既定 policy.
        """
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._beatmap_file_provider: PerformanceBeatmapFileProvider = beatmap_file_provider
        self._calculator: PerformanceCalculator = calculator
        self._completion_signal: PerformanceCompletionSignal = completion_signal
        self._settings: PerformanceRuntimeSettings = settings or PerformanceRuntimeSettings()
        self._eligibility_policy: PerformanceEligibilityPolicy = (
            eligibility_policy or PerformanceEligibilityPolicy()
        )
        self._user_stats_policy: UserStatsPolicy = user_stats_policy or UserStatsPolicy()

    async def execute(
        self,
        command: ExecutePerformanceCalculationCommand,
    ) -> ExecutePerformanceCalculationResult:
        """通信 transport に依存せず worker 側 performance calculation を実行する.

        Args:
            command (ExecutePerformanceCalculationCommand):
                claim owner,対象 calculation,基準時刻を含む command.

        Returns:
            ExecutePerformanceCalculationResult:
                completed,unavailable,pending,または競合の実行結果.

        Notes:
            PENDING_INPUT の場合は terminal 化と completion signal 通知を行わない.
        """
        claimed = await self._claim_calculation(command)
        if isinstance(claimed, ExecutePerformanceCalculationResult):
            return claimed

        file_result = await self._beatmap_file_provider.provide(
            PerformanceBeatmapFileQuery(claimed.score.beatmap_id)
        )
        if isinstance(file_result, PerformanceBeatmapFilePending):
            return ExecutePerformanceCalculationResult(
                outcome=ExecutePerformanceCalculationOutcome.PENDING_INPUT,
                calculation_id=command.calculation_id,
                score_id=claimed.score.id,
                calculation=claimed.calculation,
                pending_reason=file_result.reason,
            )

        return await self._finalize_from_file_result(
            command=command,
            claimed=claimed,
            file_result=file_result,
        )

    async def _claim_calculation(
        self,
        command: ExecutePerformanceCalculationCommand,
    ) -> _ClaimedCalculation | ExecutePerformanceCalculationResult:
        """対象 pending calculation を claim し,対応 score を解決して処理単位を返す.

        Args:
            command (ExecutePerformanceCalculationCommand):
                claim owner,calculation id,基準時刻を含む command.

        Returns:
            _ClaimedCalculation | ExecutePerformanceCalculationResult:
                処理可能な claim,または claim/terminal 競合の結果.
        """
        claim_expires_at = command.claimed_at + self._settings.claim_timeout
        async with self._unit_of_work_factory() as uow:
            claim = await uow.score_performance.claim_pending_calculation(
                ClaimScorePerformanceCalculation(
                    calculation_id=command.calculation_id,
                    owner=command.claim_owner,
                    claimed_at=command.claimed_at,
                    claim_expires_at=claim_expires_at,
                )
            )
            if claim is None:
                return ExecutePerformanceCalculationResult(
                    outcome=ExecutePerformanceCalculationOutcome.CLAIM_NOT_ACQUIRED,
                    calculation_id=command.calculation_id,
                )

            calculation = claim.calculation
            score = await uow.scores.get_by_id(calculation.score_id)
            if score is None:
                unavailable = await uow.score_performance.mark_unavailable(
                    MarkScorePerformanceCalculationUnavailable(
                        calculation_id=command.calculation_id,
                        calculator_name=self._calculator.calculator_name(),
                        calculator_version=self._calculator.calculator_version(),
                        formula_profile=calculation.formula_profile,
                        beatmap_file_attachment_id=None,
                        beatmap_file_checksum_md5=None,
                        reason="score_not_found",
                        calculated_at=command.claimed_at,
                    )
                )
                if unavailable is None:
                    return ExecutePerformanceCalculationResult(
                        outcome=ExecutePerformanceCalculationOutcome.FINALIZATION_CONFLICT,
                        calculation_id=command.calculation_id,
                        score_id=calculation.score_id,
                    )
                await uow.commit()
                result = await self._result_after_terminal_commit(unavailable)
                return ExecutePerformanceCalculationResult(
                    outcome=ExecutePerformanceCalculationOutcome.SCORE_NOT_FOUND,
                    calculation_id=result.calculation_id,
                    score_id=result.score_id,
                    calculation=result.calculation,
                    unavailable_reason=result.unavailable_reason,
                    signal_notified=result.signal_notified,
                    signal_failed=result.signal_failed,
                    signal_error=result.signal_error,
                )

            if calculation.state is PerformanceCalculationState.QUEUED:
                calculation = await uow.score_performance.update_pending_calculation_state(
                    UpdateScorePerformanceCalculationState(
                        calculation_id=command.calculation_id,
                        expected_state=PerformanceCalculationState.QUEUED,
                        state=PerformanceCalculationState.FETCHING_FILE,
                        transitioned_at=command.claimed_at,
                    )
                )
                if calculation is None:
                    return ExecutePerformanceCalculationResult(
                        outcome=ExecutePerformanceCalculationOutcome.FINALIZATION_CONFLICT,
                        calculation_id=command.calculation_id,
                        score_id=claim.calculation.score_id,
                    )

            await uow.commit()

        return _ClaimedCalculation(calculation=calculation, score=score)

    async def _transition_pending_state(
        self,
        *,
        command: ExecutePerformanceCalculationCommand,
        score_id: int,
        expected_state: PerformanceCalculationState,
        state: PerformanceCalculationState,
    ) -> PerformanceCalculation | ExecutePerformanceCalculationResult:
        """対象 calculation の pending state を期待状態から遷移させる.

        Args:
            command (ExecutePerformanceCalculationCommand):
                transition 時刻と calculation 識別子を含む command.
            score_id (int): 競合結果に記録する score 識別子.
            expected_state (PerformanceCalculationState): 更新前に要求する pending state.
            state (PerformanceCalculationState): 更新後に設定する pending state.

        Returns:
            PerformanceCalculation | ExecutePerformanceCalculationResult:
                更新済み calculation,または finalization 競合の結果.
        """
        async with self._unit_of_work_factory() as uow:
            calculation = await uow.score_performance.update_pending_calculation_state(
                UpdateScorePerformanceCalculationState(
                    calculation_id=command.calculation_id,
                    expected_state=expected_state,
                    state=state,
                    transitioned_at=command.claimed_at,
                )
            )
            if calculation is None:
                return ExecutePerformanceCalculationResult(
                    outcome=ExecutePerformanceCalculationOutcome.FINALIZATION_CONFLICT,
                    calculation_id=command.calculation_id,
                    score_id=score_id,
                )
            await uow.commit()
        return calculation

    async def _finalize_from_file_result(
        self,
        *,
        command: ExecutePerformanceCalculationCommand,
        claimed: _ClaimedCalculation,
        file_result: PerformanceBeatmapFileReady | PerformanceBeatmapFileUnavailable,
    ) -> ExecutePerformanceCalculationResult:
        """解決 file 結果に応じて calculation を terminal 化する.

        Args:
            command (ExecutePerformanceCalculationCommand):
                terminal 化の対象と基準時刻を含む command.
            claimed (_ClaimedCalculation): claim を取得済みの calculation と score.
            file_result (PerformanceBeatmapFileReady | PerformanceBeatmapFileUnavailable):
                解決済み file 入力または利用不能理由.

        Returns:
            ExecutePerformanceCalculationResult: terminal 結果,または state transition 競合の結果.
        """
        if isinstance(file_result, PerformanceBeatmapFileUnavailable):
            return await self._finalize_unavailable(
                command=command,
                score_id=claimed.calculation.score_id,
                score=claimed.score,
                calculation=claimed.calculation,
                file_result=file_result,
                reason=file_result.reason.value,
            )

        calculating = claimed.calculation
        if claimed.calculation.state is PerformanceCalculationState.FETCHING_FILE:
            transitioned = await self._transition_pending_state(
                command=command,
                score_id=claimed.calculation.score_id,
                expected_state=PerformanceCalculationState.FETCHING_FILE,
                state=PerformanceCalculationState.CALCULATING,
            )
            if isinstance(transitioned, ExecutePerformanceCalculationResult):
                return transitioned
            calculating = transitioned
        elif claimed.calculation.state is not PerformanceCalculationState.CALCULATING:
            return ExecutePerformanceCalculationResult(
                outcome=ExecutePerformanceCalculationOutcome.FINALIZATION_CONFLICT,
                calculation_id=command.calculation_id,
                score_id=claimed.calculation.score_id,
            )

        calculator_result = self._calculator.calculate(
            PerformanceCalculatorInput(
                score=claimed.score,
                osu_file_bytes=file_result.osu_file_bytes,
            )
        )
        if isinstance(calculator_result, PerformanceCalculatorUnavailable):
            return await self._finalize_unavailable(
                command=command,
                score_id=claimed.calculation.score_id,
                score=claimed.score,
                calculation=calculating,
                file_result=file_result,
                reason=calculator_result.reason.value,
            )

        return await self._finalize_completed(
            command=command,
            score_id=claimed.calculation.score_id,
            score=claimed.score,
            calculation=calculating,
            file_result=file_result,
            calculator_result=calculator_result,
        )

    async def _finalize_completed(
        self,
        *,
        command: ExecutePerformanceCalculationCommand,
        score_id: int,
        score: Score,
        calculation: PerformanceCalculation,
        file_result: PerformanceBeatmapFileReady,
        calculator_result: PerformanceCalculatorCompleted,
    ) -> ExecutePerformanceCalculationResult:
        """完了した calculator 結果を永続化し,関連 projection と signal を更新する.

        Args:
            command (ExecutePerformanceCalculationCommand):
                terminal 化の対象と基準時刻を含む command.
            score_id (int): 結果に記録する score 識別子.
            score (Score): projection 更新に使う永続 score.
            calculation (PerformanceCalculation): completed に更新する claim 済み calculation.
            file_result (PerformanceBeatmapFileReady): 使用した osu file と provenance.
            calculator_result (PerformanceCalculatorCompleted):
                calculator が返した PP と star rating.

        Returns:
            ExecutePerformanceCalculationResult: completed 結果,または finalization 競合の結果.
        """
        async with self._unit_of_work_factory() as uow:
            finalized = await uow.score_performance.mark_completed(
                CompleteScorePerformanceCalculation(
                    calculation_id=command.calculation_id,
                    pp=calculator_result.pp,
                    star_rating=calculator_result.star_rating,
                    calculator_name=self._calculator.calculator_name(),
                    calculator_version=self._calculator.calculator_version(),
                    formula_profile=calculation.formula_profile,
                    beatmap_file_attachment_id=(file_result.provenance.beatmap_file_attachment_id),
                    beatmap_file_checksum_md5=file_result.provenance.checksum_md5,
                    calculated_at=command.claimed_at,
                )
            )
            if finalized is None:
                return ExecutePerformanceCalculationResult(
                    outcome=ExecutePerformanceCalculationOutcome.FINALIZATION_CONFLICT,
                    calculation_id=command.calculation_id,
                    score_id=score_id,
                )
            _ = await refresh_performance_best_for_current_score(
                uow,
                score=score,
                calculation=finalized,
                eligibility_policy=self._eligibility_policy,
            )
            _ = await replace_current_user_stats_projection(
                uow,
                user_id=score.user_id,
                ruleset=score.ruleset,
                playstyle=score.playstyle,
                policy=self._user_stats_policy,
            )
            await uow.commit()

        result = await self._result_after_terminal_commit(finalized)
        return ExecutePerformanceCalculationResult(
            outcome=ExecutePerformanceCalculationOutcome.COMPLETED,
            calculation_id=result.calculation_id,
            score_id=result.score_id,
            calculation=result.calculation,
            signal_notified=result.signal_notified,
            signal_failed=result.signal_failed,
            signal_error=result.signal_error,
        )

    async def _finalize_unavailable(
        self,
        *,
        command: ExecutePerformanceCalculationCommand,
        score_id: int,
        score: Score,
        calculation: PerformanceCalculation,
        file_result: PerformanceBeatmapFileReady | PerformanceBeatmapFileUnavailable,
        reason: str,
    ) -> ExecutePerformanceCalculationResult:
        """利用不能理由を永続化し,関連 projection と signal を更新する.

        Args:
            command (ExecutePerformanceCalculationCommand):
                terminal 化の対象と基準時刻を含む command.
            score_id (int): 結果に記録する score 識別子.
            score (Score): projection 更新に使う永続 score.
            calculation (PerformanceCalculation): unavailable に更新する claim 済み calculation.
            file_result (PerformanceBeatmapFileReady | PerformanceBeatmapFileUnavailable):
                file provenance を含む解決結果.
            reason (str): unavailable 状態として保存する理由.

        Returns:
            ExecutePerformanceCalculationResult: unavailable 結果,または finalization 競合の結果.
        """
        provenance = file_result.provenance
        async with self._unit_of_work_factory() as uow:
            finalized = await uow.score_performance.mark_unavailable(
                MarkScorePerformanceCalculationUnavailable(
                    calculation_id=command.calculation_id,
                    calculator_name=self._calculator.calculator_name(),
                    calculator_version=self._calculator.calculator_version(),
                    formula_profile=calculation.formula_profile,
                    beatmap_file_attachment_id=(
                        None if provenance is None else provenance.beatmap_file_attachment_id
                    ),
                    beatmap_file_checksum_md5=(
                        None if provenance is None else provenance.checksum_md5
                    ),
                    reason=reason,
                    calculated_at=command.claimed_at,
                )
            )
            if finalized is None:
                return ExecutePerformanceCalculationResult(
                    outcome=ExecutePerformanceCalculationOutcome.FINALIZATION_CONFLICT,
                    calculation_id=command.calculation_id,
                    score_id=score_id,
                    unavailable_reason=reason,
                )
            _ = await refresh_performance_best_for_current_score(
                uow,
                score=score,
                calculation=finalized,
                eligibility_policy=self._eligibility_policy,
            )
            _ = await replace_current_user_stats_projection(
                uow,
                user_id=score.user_id,
                ruleset=score.ruleset,
                playstyle=score.playstyle,
                policy=self._user_stats_policy,
            )
            await uow.commit()

        result = await self._result_after_terminal_commit(finalized)
        return ExecutePerformanceCalculationResult(
            outcome=ExecutePerformanceCalculationOutcome.UNAVAILABLE,
            calculation_id=result.calculation_id,
            score_id=result.score_id,
            calculation=result.calculation,
            unavailable_reason=reason,
            signal_notified=result.signal_notified,
            signal_failed=result.signal_failed,
            signal_error=result.signal_error,
        )

    async def _result_after_terminal_commit(
        self,
        calculation: PerformanceCalculation,
    ) -> ExecutePerformanceCalculationResult:
        """永続化済み terminal calculation の completion signal を通知し,最終結果を構成する.

        Args:
            calculation (PerformanceCalculation):
                commit 済みの completed または unavailable calculation.

        Returns:
            ExecutePerformanceCalculationResult: signal 通知の成否を含む terminal 結果.

        Raises:
            ValueError:
                completion signal を送る前に calculation id が割り当てられていない場合.

        Notes:
            signal 通知の例外は durable terminal 結果を rollback せず,
            結果の signal_failed に記録する.
        """
        calculation_id = calculation.id
        if calculation_id is None:
            msg = "performance calculation id must be assigned before completion signal"
            raise ValueError(msg)

        signal_failed = False
        signal_error: str | None = None
        try:
            await self._completion_signal.notify(
                PerformanceCompletionSignalPayload(
                    score_id=calculation.score_id,
                    calculation_id=calculation_id,
                    state=calculation.state,
                )
            )
        except Exception as exc:
            signal_failed = True
            signal_error = str(exc)

        return ExecutePerformanceCalculationResult(
            outcome=(
                ExecutePerformanceCalculationOutcome.COMPLETED
                if calculation.state is PerformanceCalculationState.COMPLETED
                else ExecutePerformanceCalculationOutcome.UNAVAILABLE
            ),
            calculation_id=calculation_id,
            score_id=calculation.score_id,
            calculation=calculation,
            unavailable_reason=calculation.unavailable_reason,
            signal_notified=not signal_failed,
            signal_failed=signal_failed,
            signal_error=signal_error,
        )


__all__ = (
    "ExecutePerformanceCalculationCommand",
    "ExecutePerformanceCalculationOutcome",
    "ExecutePerformanceCalculationResult",
    "ExecutePerformanceCalculationUseCase",
)
