"""durable なスコア performance recalculation batch work を処理する."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, final

from osu_server.domain.scores.performance import PerformanceCalculationState
from osu_server.repositories.interfaces.commands.score_performance import (
    ClaimScorePerformanceRecalculationWork,
    CompleteScorePerformanceRecalculationWork,
    MarkScorePerformanceRecalculationWorkFailed,
    MarkScorePerformanceRecalculationWorkUnavailable,
)
from osu_server.services.commands.scores.performance.runtime import PerformanceRuntimeSettings

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.performance import PerformanceRecalculationWorkItem
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
    from osu_server.services.commands.scores.performance.create_recalculation_batch import (
        PerformanceCalculatorIdentity,
    )
    from osu_server.services.commands.scores.performance.request_calculation import (
        RequestPerformanceCalculationResult,
    )

from osu_server.services.commands.scores.performance.request_calculation import (
    RequestPerformanceCalculationCommand,
)


class ProcessPerformanceRecalculationBatchOutcome(Enum):
    """1回の bounded recalculation batch processing pass の観測可能な結果を表す.

    Attributes:
        PROCESSED (ProcessPerformanceRecalculationBatchOutcome):
            1件以上の claimed work を処理した結果.
        NO_WORK (ProcessPerformanceRecalculationBatchOutcome):
            claim 可能な work がなかった結果.
    """

    PROCESSED = "processed"
    NO_WORK = "no_work"


@dataclass(frozen=True, slots=True)
class ProcessPerformanceRecalculationBatchCommand:
    """1回の recalculation batch worker pass を指示する command を表す.

    Attributes:
        batch_id (int): 処理する recalculation batch の正の永続識別子.
        claim_owner (str): work を所有する worker の空でない識別子.
        claimed_at (datetime): claim と work terminal 化の基準時刻.
    """

    batch_id: int
    claim_owner: str
    claimed_at: datetime

    def __post_init__(self) -> None:
        """対象 batch id と claim owner の入力制約を検証する.

        Returns:
            None: command の不変条件を検証し,呼び出し側へ値を返さずに完了する.

        Raises:
            ValueError: batch_id が0以下,または claim_owner が空文字列の場合.
        """
        if self.batch_id <= 0:
            msg = "batch_id must be positive"
            raise ValueError(msg)
        if self.claim_owner == "":
            msg = "claim_owner must not be empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ProcessPerformanceRecalculationBatchResult:
    """1回の recalculation batch processing pass の型付き結果を表す.

    Attributes:
        outcome (ProcessPerformanceRecalculationBatchOutcome): work の有無と処理結果.
        batch_id (int): command が対象にした recalculation batch 識別子.
        claimed_count (int): この pass で claim した work item 数.
        completed_count (int): replacement calculation が completed となった work item 数.
        unavailable_count (int): replacement calculation が unavailable となった work item 数.
        retryable_failure_count (int): 再試行可能な failure として記録した work item 数.
        finalization_conflict_count (int): work terminal 化で競合した work item 数.
    """

    outcome: ProcessPerformanceRecalculationBatchOutcome
    batch_id: int
    claimed_count: int = 0
    completed_count: int = 0
    unavailable_count: int = 0
    retryable_failure_count: int = 0
    finalization_conflict_count: int = 0


class PerformanceCalculationRequester(Protocol):
    """recalculation batch processing が必要とする calculation request use-case 境界を表す."""

    async def execute(
        self,
        command: RequestPerformanceCalculationCommand,
    ) -> RequestPerformanceCalculationResult:
        """1件の score の replacement performance calculation を要求する.

        Args:
            command (RequestPerformanceCalculationCommand):
                replacement の対象 score と calculator provenance.

        Returns:
            RequestPerformanceCalculationResult: calculation の作成,再利用,または失敗を表す結果.
        """
        ...


@final
class ProcessPerformanceRecalculationBatchUseCase:
    """durable recalculation work を claim し,replacement calculation request を実行する."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        request_use_case: PerformanceCalculationRequester,
        calculator_identity: PerformanceCalculatorIdentity,
        settings: PerformanceRuntimeSettings | None = None,
    ) -> None:
        """対象 work の claim,replacement request,calculator provenance の dependency を受け取る.

        Args:
            unit_of_work_factory (UnitOfWorkFactory):
                work claim と terminal 化を行う command Unit of Work factory.
            request_use_case (PerformanceCalculationRequester):
                replacement calculation を作成または再利用する境界.
            calculator_identity (PerformanceCalculatorIdentity):
                replacement request の calculator provenance を提供する境界.
            settings (PerformanceRuntimeSettings | None):
                claim timeout と worker chunk size の設定. 未指定時は既定値.
        """
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._request_use_case: PerformanceCalculationRequester = request_use_case
        self._calculator_identity: PerformanceCalculatorIdentity = calculator_identity
        self._settings: PerformanceRuntimeSettings = settings or PerformanceRuntimeSettings()

    async def execute(
        self,
        command: ProcessPerformanceRecalculationBatchCommand,
    ) -> ProcessPerformanceRecalculationBatchResult:
        """未処理または stale な recalculation work の bounded chunk を1回処理する.

        Args:
            command (ProcessPerformanceRecalculationBatchCommand):
                batch,claim owner,基準時刻を含む command.

        Returns:
            ProcessPerformanceRecalculationBatchResult: claim 件数と terminal/retryable 結果の集計.
        """
        claimed = await self._claim_work(command)
        if len(claimed) == 0:
            return ProcessPerformanceRecalculationBatchResult(
                outcome=ProcessPerformanceRecalculationBatchOutcome.NO_WORK,
                batch_id=command.batch_id,
            )

        completed_count = 0
        unavailable_count = 0
        retryable_failure_count = 0
        finalization_conflict_count = 0

        for work_item in claimed:
            request_result = await self._request_replacement_calculation(command, work_item)
            outcome = await self._record_work_outcome(
                command=command,
                work_item=work_item,
                request_result=request_result,
            )
            if outcome is _WorkOutcome.COMPLETED:
                completed_count += 1
            elif outcome is _WorkOutcome.UNAVAILABLE:
                unavailable_count += 1
            elif outcome is _WorkOutcome.RETRYABLE_FAILURE:
                retryable_failure_count += 1
            else:
                finalization_conflict_count += 1

        return ProcessPerformanceRecalculationBatchResult(
            outcome=ProcessPerformanceRecalculationBatchOutcome.PROCESSED,
            batch_id=command.batch_id,
            claimed_count=len(claimed),
            completed_count=completed_count,
            unavailable_count=unavailable_count,
            retryable_failure_count=retryable_failure_count,
            finalization_conflict_count=finalization_conflict_count,
        )

    async def _claim_work(
        self,
        command: ProcessPerformanceRecalculationBatchCommand,
    ) -> tuple[PerformanceRecalculationWorkItem, ...]:
        """指定 batch から bounded な再計算 work を claim して commit する.

        Args:
            command (ProcessPerformanceRecalculationBatchCommand):
                claim 条件と対象 batch を含む command.

        Returns:
            tuple[PerformanceRecalculationWorkItem, ...]:
                この worker が処理する claim 済み work item.
        """
        async with self._unit_of_work_factory() as uow:
            claimed = await uow.score_performance.claim_recalculation_work(
                ClaimScorePerformanceRecalculationWork(
                    batch_id=command.batch_id,
                    owner=command.claim_owner,
                    claimed_at=command.claimed_at,
                    claim_expires_at=command.claimed_at + self._settings.claim_timeout,
                    limit=self._settings.worker_chunk_size,
                )
            )
            await uow.commit()
        return claimed

    async def _request_replacement_calculation(
        self,
        command: ProcessPerformanceRecalculationBatchCommand,
        work_item: PerformanceRecalculationWorkItem,
    ) -> RequestPerformanceCalculationResult:
        """1件の work item 用 replacement performance calculation を要求する.

        Args:
            command (ProcessPerformanceRecalculationBatchCommand):
                calculator provenance の基準時刻を含む command.
            work_item (PerformanceRecalculationWorkItem):
                replacement request を作る claim 済み work.

        Returns:
            RequestPerformanceCalculationResult: request use-case が返した calculation 結果.
        """
        return await self._request_use_case.execute(
            RequestPerformanceCalculationCommand(
                score_id=work_item.score_id,
                calculator_name=self._calculator_identity.calculator_name(),
                calculator_version=self._calculator_identity.calculator_version(),
                requested_at=command.claimed_at,
            )
        )

    async def _record_work_outcome(
        self,
        *,
        command: ProcessPerformanceRecalculationBatchCommand,
        work_item: PerformanceRecalculationWorkItem,
        request_result: RequestPerformanceCalculationResult,
    ) -> _WorkOutcome:
        """対象 work item の replacement calculation 結果を記録する.

        Args:
            command (ProcessPerformanceRecalculationBatchCommand):
                work terminal 化の owner と時刻を含む command.
            work_item (PerformanceRecalculationWorkItem):
                結果を記録する claim 済み work.
            request_result (RequestPerformanceCalculationResult):
                replacement calculation request の結果.

        Returns:
            _WorkOutcome:
                completed,unavailable,retryable failure,または finalization conflict の分類.
        """
        calculation = request_result.calculation
        if calculation is None:
            return await self._mark_work_failed(
                command=command,
                work_item=work_item,
                error=request_result.outcome.value,
            )
        if calculation.score_id != work_item.score_id:
            return await self._mark_work_failed(
                command=command,
                work_item=work_item,
                error="calculation_score_mismatch",
            )
        if calculation.state is PerformanceCalculationState.COMPLETED:
            return await self._mark_work_completed(
                command=command,
                work_item=work_item,
                calculation_id=_require_calculation_id(calculation.id),
            )
        if calculation.state is PerformanceCalculationState.UNAVAILABLE:
            return await self._mark_work_unavailable(
                command=command,
                work_item=work_item,
                calculation_id=_require_calculation_id(calculation.id),
                reason=calculation.unavailable_reason or "performance_unavailable",
            )
        if calculation.state.is_pending:
            return await self._mark_work_failed(
                command=command,
                work_item=work_item,
                error="replacement_calculation_pending",
            )
        return await self._mark_work_failed(
            command=command,
            work_item=work_item,
            error="replacement_calculation_not_terminal",
        )

    async def _mark_work_completed(
        self,
        *,
        command: ProcessPerformanceRecalculationBatchCommand,
        work_item: PerformanceRecalculationWorkItem,
        calculation_id: int,
    ) -> _WorkOutcome:
        """対象 work item を completed replacement calculation として terminal 化する.

        Args:
            command (ProcessPerformanceRecalculationBatchCommand):
                terminal 化の owner と時刻を含む command.
            work_item (PerformanceRecalculationWorkItem): completed に更新する claim 済み work.
            calculation_id (int): completed replacement calculation の永続識別子.

        Returns:
            _WorkOutcome: completed,または owner/state 競合を示す finalization conflict.
        """
        async with self._unit_of_work_factory() as uow:
            updated = await uow.score_performance.mark_recalculation_work_completed(
                CompleteScorePerformanceRecalculationWork(
                    work_item_id=_require_work_item_id(work_item.id),
                    owner=command.claim_owner,
                    calculation_id=calculation_id,
                    completed_at=command.claimed_at,
                )
            )
            if updated is None:
                return _WorkOutcome.FINALIZATION_CONFLICT
            await uow.commit()
        return _WorkOutcome.COMPLETED

    async def _mark_work_unavailable(
        self,
        *,
        command: ProcessPerformanceRecalculationBatchCommand,
        work_item: PerformanceRecalculationWorkItem,
        calculation_id: int,
        reason: str,
    ) -> _WorkOutcome:
        """対象 work item を unavailable replacement calculation として terminal 化する.

        Args:
            command (ProcessPerformanceRecalculationBatchCommand):
                terminal 化の owner と時刻を含む command.
            work_item (PerformanceRecalculationWorkItem): unavailable に更新する claim 済み work.
            calculation_id (int): unavailable replacement calculation の永続識別子.
            reason (str): unavailable 状態として保存する理由.

        Returns:
            _WorkOutcome: unavailable,または owner/state 競合を示す finalization conflict.
        """
        async with self._unit_of_work_factory() as uow:
            updated = await uow.score_performance.mark_recalculation_work_unavailable(
                MarkScorePerformanceRecalculationWorkUnavailable(
                    work_item_id=_require_work_item_id(work_item.id),
                    owner=command.claim_owner,
                    calculation_id=calculation_id,
                    reason=reason,
                    completed_at=command.claimed_at,
                )
            )
            if updated is None:
                return _WorkOutcome.FINALIZATION_CONFLICT
            await uow.commit()
        return _WorkOutcome.UNAVAILABLE

    async def _mark_work_failed(
        self,
        *,
        command: ProcessPerformanceRecalculationBatchCommand,
        work_item: PerformanceRecalculationWorkItem,
        error: str,
    ) -> _WorkOutcome:
        """対象 work item を再試行可能な failure として記録する.

        Args:
            command (ProcessPerformanceRecalculationBatchCommand):
                failure 記録の owner と時刻を含む command.
            work_item (PerformanceRecalculationWorkItem): failure に更新する claim 済み work.
            error (str): 後続処理で診断する failure 種別.

        Returns:
            _WorkOutcome: retryable failure,または owner/state 競合を示す finalization conflict.
        """
        async with self._unit_of_work_factory() as uow:
            updated = await uow.score_performance.mark_recalculation_work_failed(
                MarkScorePerformanceRecalculationWorkFailed(
                    work_item_id=_require_work_item_id(work_item.id),
                    owner=command.claim_owner,
                    error=error,
                    failed_at=command.claimed_at,
                )
            )
            if updated is None:
                return _WorkOutcome.FINALIZATION_CONFLICT
            await uow.commit()
        return _WorkOutcome.RETRYABLE_FAILURE


class _WorkOutcome(Enum):
    """個別 recalculation work item の記録結果を分類する内部 enum を表す.

    Attributes:
        COMPLETED (_WorkOutcome):
            replacement calculation が completed で terminal 化された状態.
        UNAVAILABLE (_WorkOutcome):
            replacement calculation が unavailable で terminal 化された状態.
        RETRYABLE_FAILURE (_WorkOutcome): 後続 pass で再試行できる failure を記録した状態.
        FINALIZATION_CONFLICT (_WorkOutcome):
            owner または state の競合で terminal 化できない状態.
    """

    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    RETRYABLE_FAILURE = "retryable_failure"
    FINALIZATION_CONFLICT = "finalization_conflict"


def _require_calculation_id(calculation_id: int | None) -> int:
    """完了処理に必要な calculation id が割り当て済みであることを確認する.

    Args:
        calculation_id (int | None): replacement calculation の永続識別子. 未採番時はNone.

    Returns:
        int: 割り当て済みの calculation 識別子.

    Raises:
        ValueError: calculation id がまだ割り当てられていない場合.
    """
    if calculation_id is None:
        msg = "performance calculation id must be assigned before work finalization"
        raise ValueError(msg)
    return calculation_id


def _require_work_item_id(work_item_id: int | None) -> int:
    """完了処理に必要な work item id が割り当て済みであることを確認する.

    Args:
        work_item_id (int | None): recalculation work item の永続識別子. 未採番時はNone.

    Returns:
        int: 割り当て済みの work item 識別子.

    Raises:
        ValueError: work item id がまだ割り当てられていない場合.
    """
    if work_item_id is None:
        msg = "recalculation work item id must be assigned before finalization"
        raise ValueError(msg)
    return work_item_id


__all__ = (
    "PerformanceCalculationRequester",
    "ProcessPerformanceRecalculationBatchCommand",
    "ProcessPerformanceRecalculationBatchOutcome",
    "ProcessPerformanceRecalculationBatchResult",
    "ProcessPerformanceRecalculationBatchUseCase",
)
