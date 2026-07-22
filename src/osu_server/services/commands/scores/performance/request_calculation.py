"""スコア performance calculation を要求する command use-case を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, final

from osu_server.domain.scores.performance import (
    FormulaProfilePolicy,
    PerformanceEligibilityPolicy,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    CreateScorePerformanceCalculation,
    ScorePerformanceCommandConflictError,
)

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.performance import PerformanceCalculation
    from osu_server.repositories.interfaces.commands.score_performance import (
        ScorePerformanceCalculationRequestResult,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory


class RequestPerformanceCalculationOutcome(Enum):
    """performance calculation request command の観測可能な結果を表す.

    Attributes:
        CREATED (RequestPerformanceCalculationOutcome):
            新しい calculation を作成した結果.
        CREATED_REPLACEMENT (RequestPerformanceCalculationOutcome):
            stale な current を置き換える calculation を作成した結果.
        REUSED_PENDING (RequestPerformanceCalculationOutcome):
            既存 pending calculation を再利用した結果.
        REUSED_REPLACEMENT_PENDING (RequestPerformanceCalculationOutcome):
            既存 pending replacement を再利用した結果.
        ALREADY_CURRENT (RequestPerformanceCalculationOutcome):
            同一 provenance の terminal calculation が current な結果.
        SKIPPED_OUT_OF_SCOPE (RequestPerformanceCalculationOutcome):
            score が performance 対象外である結果.
        SCORE_NOT_FOUND (RequestPerformanceCalculationOutcome):
            対象 score が存在しない結果.
        TEMPORARY_CONFLICT (RequestPerformanceCalculationOutcome):
            durable request 作成が一時的に競合した結果.
    """

    CREATED = "created"
    CREATED_REPLACEMENT = "created_replacement"
    REUSED_PENDING = "reused_pending"
    REUSED_REPLACEMENT_PENDING = "reused_replacement_pending"
    ALREADY_CURRENT = "already_current"
    SKIPPED_OUT_OF_SCOPE = "skipped_out_of_scope"
    SCORE_NOT_FOUND = "score_not_found"
    TEMPORARY_CONFLICT = "temporary_conflict"


@dataclass(frozen=True, slots=True)
class RequestPerformanceCalculationCommand:
    """1件の accepted score の performance calculation を要求する command を表す.

    Attributes:
        score_id (int): calculation を要求する accepted score の永続識別子.
        calculator_name (str): calculation provenance に記録する calculator implementation 名.
        calculator_version (str):
            calculation provenance に記録する calculator implementation version.
        requested_at (datetime): request と calculation 作成の基準時刻.
    """

    score_id: int
    calculator_name: str
    calculator_version: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class RequestPerformanceCalculationResult:
    """performance calculation request workflow の型付き結果を表す.

    Attributes:
        outcome (RequestPerformanceCalculationOutcome): 作成、再利用、対象外、競合の結果種別.
        score_id (int): command が対象にした score 識別子.
        calculation (PerformanceCalculation | None):
            作成または再利用した calculation. 作成不能時はNone.
        eligibility_reason (str | None): performance 対象外と判定した理由. 該当しない場合はNone.
        created (bool): 新しい durable calculation row を作成したか.
        is_replacement (bool): current calculation の replacement として扱うか.
        worker_wake_requested (bool): pending calculation の worker 起動を要求したか.
        worker_wake_failed (bool): worker 起動要求で例外を捕捉したか.
        worker_wake_error (str | None): 捕捉した worker 起動例外の文字列. 未発生時はNone.
    """

    outcome: RequestPerformanceCalculationOutcome
    score_id: int
    calculation: PerformanceCalculation | None = None
    eligibility_reason: str | None = None
    created: bool = False
    is_replacement: bool = False
    worker_wake_requested: bool = False
    worker_wake_failed: bool = False
    worker_wake_error: str | None = None


class PerformanceCalculationWorkerWake(Protocol):
    """calculation worker を起動する adapter 非依存境界を表す."""

    async def wake_score_calculation(self, *, score_id: int, calculation_id: int) -> None:
        """作成済み durable calculation row の score performance 処理開始を要求する.

        Args:
            score_id (int): 処理対象 calculation が属する score の永続識別子.
            calculation_id (int): 処理対象の durable performance calculation 識別子.

        Returns:
            None: worker 起動を要求し、呼び出し側へ値を返さずに完了する.
        """
        ...


@final
class NoopPerformanceCalculationWorkerWake:
    """taskiq job wiring 前に使う no-op calculation worker wake 境界を表す."""

    async def wake_score_calculation(self, *, score_id: int, calculation_id: int) -> None:
        """外部 worker 起動を要求せずに完了する.

        Args:
            score_id (int): 破棄する score 識別子.
            calculation_id (int): 破棄する calculation 識別子.

        Returns:
            None: 外部 worker を起動せず、呼び出し側へ値を返さずに完了する.
        """
        _ = score_id
        _ = calculation_id


class RequestPerformanceCalculationUseCase:
    """1件の score 用 durable performance calculation request を作成または再利用する."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        worker_wake: PerformanceCalculationWorkerWake | None = None,
        eligibility_policy: PerformanceEligibilityPolicy | None = None,
        formula_profile_policy: FormulaProfilePolicy | None = None,
    ) -> None:
        """永続 request と worker 起動に必要な dependency を受け取る.

        Args:
            unit_of_work_factory (UnitOfWorkFactory):
                score と calculation を整合的に扱う command Unit of Work factory.
            worker_wake (PerformanceCalculationWorkerWake | None):
                pending calculation の worker を起動する境界. 未指定時は no-op.
            eligibility_policy (PerformanceEligibilityPolicy | None):
                score の performance 対象可否を判定する policy. 未指定時は既定 policy.
            formula_profile_policy (FormulaProfilePolicy | None):
                score playstyle の formula profile を決める policy. 未指定時は既定 policy.
        """
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._worker_wake: PerformanceCalculationWorkerWake = (
            worker_wake or NoopPerformanceCalculationWorkerWake()
        )
        self._eligibility_policy: PerformanceEligibilityPolicy = (
            eligibility_policy or PerformanceEligibilityPolicy()
        )
        self._formula_profile_policy: FormulaProfilePolicy = (
            formula_profile_policy or FormulaProfilePolicy()
        )

    async def execute(
        self,
        command: RequestPerformanceCalculationCommand,
    ) -> RequestPerformanceCalculationResult:
        """永続化 boundary 内で calculation request workflow を実行する.

        Args:
            command (RequestPerformanceCalculationCommand):
                score、calculator provenance、要求時刻を含む command.

        Returns:
            RequestPerformanceCalculationResult:
                calculation の作成、再利用、対象外、または一時競合の結果.

        Notes:
            durable mutation を commit してから worker 起動を試み、起動例外は結果に記録する.
        """
        async with self._unit_of_work_factory() as uow:
            score = await uow.scores.get_by_id(command.score_id)
            if score is None:
                return RequestPerformanceCalculationResult(
                    outcome=RequestPerformanceCalculationOutcome.SCORE_NOT_FOUND,
                    score_id=command.score_id,
                )

            eligibility = self._eligibility_policy.evaluate(score)
            if not eligibility.is_eligible:
                return RequestPerformanceCalculationResult(
                    outcome=RequestPerformanceCalculationOutcome.SKIPPED_OUT_OF_SCOPE,
                    score_id=command.score_id,
                    eligibility_reason=eligibility.reason,
                )

            formula_profile = self._formula_profile_policy.active_profile_for(score.playstyle)
            try:
                request_result = await uow.score_performance.create_or_reuse_calculation(
                    CreateScorePerformanceCalculation(
                        score_id=command.score_id,
                        calculator_name=command.calculator_name,
                        calculator_version=command.calculator_version,
                        formula_profile=formula_profile,
                        requested_at=command.requested_at,
                    )
                )
            except ScorePerformanceCommandConflictError:
                return RequestPerformanceCalculationResult(
                    outcome=RequestPerformanceCalculationOutcome.TEMPORARY_CONFLICT,
                    score_id=command.score_id,
                )

            if request_result.requires_commit:
                await uow.commit()

        return await self._result_after_commit(command.score_id, request_result)

    async def _result_after_commit(
        self,
        score_id: int,
        request_result: ScorePerformanceCalculationRequestResult,
    ) -> RequestPerformanceCalculationResult:
        """永続化後の request 結果から worker 起動状態を含む応答を構成する.

        Args:
            score_id (int): calculation が属する score の永続識別子.
            request_result (ScorePerformanceCalculationRequestResult):
                durable request 作成または再利用の結果.

        Returns:
            RequestPerformanceCalculationResult: outcome と worker 起動成否を含む型付き結果.

        Raises:
            ValueError:
                pending calculation を起動する前に calculation id が割り当てられていない場合.

        Notes:
            worker 起動例外は durable calculation row を rollback せず結果へ記録する.
        """
        outcome = _outcome_from_request_result(request_result)
        should_wake = request_result.calculation.state.is_pending
        wake_failed = False
        wake_error: str | None = None

        if should_wake:
            calculation_id = request_result.calculation.id
            if calculation_id is None:
                msg = "performance calculation id must be assigned before worker wake"
                raise ValueError(msg)
            try:
                await self._worker_wake.wake_score_calculation(
                    score_id=score_id,
                    calculation_id=calculation_id,
                )
            except Exception as exc:
                wake_failed = True
                wake_error = str(exc)

        return RequestPerformanceCalculationResult(
            outcome=outcome,
            score_id=score_id,
            calculation=request_result.calculation,
            created=request_result.created,
            is_replacement=request_result.is_replacement,
            worker_wake_requested=should_wake,
            worker_wake_failed=wake_failed,
            worker_wake_error=wake_error,
        )


def _outcome_from_request_result(
    request_result: ScorePerformanceCalculationRequestResult,
) -> RequestPerformanceCalculationOutcome:
    """永続 request 結果を公開 request outcome へ変換する.

    Args:
        request_result (ScorePerformanceCalculationRequestResult):
            created、replacement、state を含む durable 結果.

    Returns:
        RequestPerformanceCalculationOutcome:
            作成、再利用、または current 判定に対応する公開 outcome.
    """
    if request_result.created:
        if request_result.is_replacement:
            return RequestPerformanceCalculationOutcome.CREATED_REPLACEMENT
        return RequestPerformanceCalculationOutcome.CREATED

    if request_result.calculation.state.is_pending:
        if request_result.is_replacement:
            return RequestPerformanceCalculationOutcome.REUSED_REPLACEMENT_PENDING
        return RequestPerformanceCalculationOutcome.REUSED_PENDING

    return RequestPerformanceCalculationOutcome.ALREADY_CURRENT


__all__ = (
    "NoopPerformanceCalculationWorkerWake",
    "PerformanceCalculationWorkerWake",
    "RequestPerformanceCalculationCommand",
    "RequestPerformanceCalculationOutcome",
    "RequestPerformanceCalculationResult",
    "RequestPerformanceCalculationUseCase",
)
