"""スコア performance recalculation batch を作成する command use-case を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, final

from osu_server.domain.scores.performance import FormulaProfilePolicy
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.score_performance import (
    CreateScorePerformanceRecalculationBatch,
    CreateScorePerformanceRecalculationWorkItem,
)
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceCandidateSelection,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from osu_server.domain.scores.performance import (
        FormulaProfile,
        PerformanceRecalculationBatch,
        RecalculationCandidateReason,
    )
    from osu_server.repositories.interfaces.queries.score_performance import (
        ScorePerformanceQueryRepository,
        ScorePerformanceRecalculationCandidateResult,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory


class CreatePerformanceRecalculationBatchMode(Enum):
    """operator が選択する recalculation batch の実行 mode を表す.

    Attributes:
        DRY_RUN (CreatePerformanceRecalculationBatchMode):
            durable work を作成せず候補だけ集計する mode.
        EXECUTE (CreatePerformanceRecalculationBatchMode):
            durable batch と work item を作成する mode.
    """

    DRY_RUN = "dry_run"
    EXECUTE = "execute"


class CreatePerformanceRecalculationBatchOutcome(Enum):
    """recalculation batch 作成 workflow の観測可能な結果を表す.

    Attributes:
        DRY_RUN (CreatePerformanceRecalculationBatchOutcome): 候補選択のみを完了した結果.
        CREATED (CreatePerformanceRecalculationBatchOutcome): durable batch を作成した結果.
        REJECTED (CreatePerformanceRecalculationBatchOutcome): full scope 確認不足で拒否した結果.
    """

    DRY_RUN = "dry_run"
    CREATED = "created"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class CreatePerformanceRecalculationBatchCommand:
    """durable recalculation work の選択または作成を指示する command を表す.

    Attributes:
        mode (CreatePerformanceRecalculationBatchMode): dry run か durable batch 作成かを示す mode.
        score_id (int | None): 対象を1 score に絞る識別子. 未指定時はNone.
        beatmap_id (int | None): 対象を1 beatmap に絞る識別子. 未指定時はNone.
        user_id (int | None): 対象を1 user に絞る識別子. 未指定時はNone.
        ruleset (Ruleset | None): 対象を ruleset に絞る条件. 未指定時はNone.
        limit (int | None): 選択候補数の上限. 未指定時はNone.
        full_scope (bool): filter なし execute を明示確認したか.
        include_unavailable (bool): unavailable calculation も候補に含めるか.
        requested_at (datetime): batch 作成と candidate 判定の基準時刻.
    """

    mode: CreatePerformanceRecalculationBatchMode
    score_id: int | None
    beatmap_id: int | None
    user_id: int | None
    ruleset: Ruleset | None
    limit: int | None
    full_scope: bool
    include_unavailable: bool
    requested_at: datetime

    def __post_init__(self) -> None:
        """任意の数値 filter が指定時に正であることを検証する.

        Returns:
            None: filter 値を検証し、呼び出し側へ値を返さずに完了する.

        Raises:
            ValueError: score_id、beatmap_id、user_id、または limit が0以下の場合.
        """
        _validate_optional_positive("score_id", self.score_id)
        _validate_optional_positive("beatmap_id", self.beatmap_id)
        _validate_optional_positive("user_id", self.user_id)
        _validate_optional_positive("limit", self.limit)


@dataclass(frozen=True, slots=True)
class CreatePerformanceRecalculationBatchResult:
    """Dry-runまたは永続batch作成の結果.

    Attributes:
        outcome (CreatePerformanceRecalculationBatchOutcome): 実行結果の種別.
        candidate_count (int): 選択された候補件数.
        reason_counts (Mapping[RecalculationCandidateReason, int]): 理由別候補件数.
        filters (Mapping[str, object]): 実行に使用したfilter snapshot.
        target_calculator_name (str): 対象calculator名.
        target_calculator_version (str): 対象calculator version.
        target_formula_profile (FormulaProfile): 対象formula profile.
        batch (PerformanceRecalculationBatch | None): 作成済みbatch. 未作成時はNone.
        worker_wake_requested (bool): Worker起動を要求したか.
        worker_wake_failed (bool): Worker起動要求が失敗したか.
        worker_wake_error (str | None): Worker起動error. 未発生時はNone.
        rejection_reason (str | None): 作成拒否理由. 拒否されなければNone.
    """

    outcome: CreatePerformanceRecalculationBatchOutcome
    candidate_count: int
    reason_counts: Mapping[RecalculationCandidateReason, int]
    filters: Mapping[str, object]
    target_calculator_name: str
    target_calculator_version: str
    target_formula_profile: FormulaProfile
    batch: PerformanceRecalculationBatch | None = None
    worker_wake_requested: bool = False
    worker_wake_failed: bool = False
    worker_wake_error: str | None = None
    rejection_reason: str | None = None


class PerformanceCalculatorIdentity(Protocol):
    """adapter 非依存の performance calculator identity 境界を表す."""

    def calculator_name(self) -> str:
        """有効な calculator implementation 名を返す.

        Returns:
            str: calculation provenance に記録する calculator 名.
        """
        ...

    def calculator_version(self) -> str:
        """有効な calculator implementation version を返す.

        Returns:
            str: calculation provenance に記録する calculator version.
        """
        ...


class PerformanceRecalculationBatchWorkerWake(Protocol):
    """recalculation batch worker を起動する adapter 非依存境界を表す."""

    async def wake_recalculation_batch(self, *, batch_id: int) -> None:
        """作成済み durable recalculation batch の処理開始を要求する.

        Args:
            batch_id (int): 処理対象の作成済み recalculation batch 識別子.

        Returns:
            None: worker 起動を要求し、呼び出し側へ値を返さずに完了する.
        """
        ...


@final
class NoopPerformanceRecalculationBatchWorkerWake:
    """taskiq batch processing を接続する前に使う no-op worker wake 境界を表す."""

    async def wake_recalculation_batch(self, *, batch_id: int) -> None:
        """外部 worker 起動を要求せずに完了する.

        Args:
            batch_id (int): 破棄する recalculation batch 識別子.

        Returns:
            None: 外部 worker を起動せず、呼び出し側へ値を返さずに完了する.
        """
        _ = batch_id


class CreatePerformanceRecalculationBatchUseCase:
    """候補を選択し、必要に応じて durable recalculation batch work を作成する."""

    def __init__(
        self,
        *,
        query_repository: ScorePerformanceQueryRepository,
        unit_of_work_factory: UnitOfWorkFactory,
        calculator_identity: PerformanceCalculatorIdentity,
        worker_wake: PerformanceRecalculationBatchWorkerWake | None = None,
        formula_profile_policy: FormulaProfilePolicy | None = None,
    ) -> None:
        """候補選択、永続化、worker 起動に必要な dependency を受け取る.

        Args:
            query_repository (ScorePerformanceQueryRepository):
                recalculation candidate を選択する query repository.
            unit_of_work_factory (UnitOfWorkFactory):
                durable batch を作成する command Unit of Work factory.
            calculator_identity (PerformanceCalculatorIdentity):
                対象 calculator の name と version を提供する境界.
            worker_wake (PerformanceRecalculationBatchWorkerWake | None):
                作成後に worker を起動する境界. 未指定時は no-op.
            formula_profile_policy (FormulaProfilePolicy | None):
                VANILLA の target formula profile を決める policy. 未指定時は既定 policy.
        """
        self._query_repository: ScorePerformanceQueryRepository = query_repository
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._calculator_identity: PerformanceCalculatorIdentity = calculator_identity
        self._worker_wake: PerformanceRecalculationBatchWorkerWake = (
            worker_wake or NoopPerformanceRecalculationBatchWorkerWake()
        )
        self._formula_profile_policy: FormulaProfilePolicy = (
            formula_profile_policy or FormulaProfilePolicy()
        )

    async def execute(
        self,
        command: CreatePerformanceRecalculationBatchCommand,
    ) -> CreatePerformanceRecalculationBatchResult:
        """Dry-run候補選択または永続batch作成を実行する.

        Args:
            command (CreatePerformanceRecalculationBatchCommand): Scope、mode、要求日時.

        Returns:
            CreatePerformanceRecalculationBatchResult: 候補集計とbatch作成結果.

        Raises:
            ValueError: 永続化後のbatch IDがworker起動前に割り当てられていない場合.

        Notes:
            Full-scope確認がない危険な要求はrepositoryを開かずREJECTEDで返す.
        """
        filters = _filters_from_command(command)
        target_calculator_name = self._calculator_identity.calculator_name()
        target_calculator_version = self._calculator_identity.calculator_version()
        target_formula_profile = self._formula_profile_policy.active_profile_for(Playstyle.VANILLA)

        if _requires_full_scope_confirmation(command):
            return CreatePerformanceRecalculationBatchResult(
                outcome=CreatePerformanceRecalculationBatchOutcome.REJECTED,
                candidate_count=0,
                reason_counts={},
                filters=filters,
                target_calculator_name=target_calculator_name,
                target_calculator_version=target_calculator_version,
                target_formula_profile=target_formula_profile,
                rejection_reason="full_scope_required",
            )

        selection = ScorePerformanceCandidateSelection(
            target_calculator_name=target_calculator_name,
            target_calculator_version=target_calculator_version,
            target_formula_profile=target_formula_profile,
            score_id=command.score_id,
            beatmap_id=command.beatmap_id,
            user_id=command.user_id,
            ruleset=command.ruleset,
            limit=command.limit,
            include_unavailable=command.include_unavailable,
        )
        selected = await self._query_repository.select_recalculation_candidates(selection)
        reason_counts = dict(selected.reason_counts)

        if command.mode is CreatePerformanceRecalculationBatchMode.DRY_RUN:
            return CreatePerformanceRecalculationBatchResult(
                outcome=CreatePerformanceRecalculationBatchOutcome.DRY_RUN,
                candidate_count=selected.candidate_count,
                reason_counts=reason_counts,
                filters=filters,
                target_calculator_name=target_calculator_name,
                target_calculator_version=target_calculator_version,
                target_formula_profile=target_formula_profile,
            )

        return await self._create_batch(
            command=command,
            selected=selected,
            reason_counts=reason_counts,
            filters=filters,
            target_calculator_name=target_calculator_name,
            target_calculator_version=target_calculator_version,
            target_formula_profile=target_formula_profile,
        )

    async def _create_batch(
        self,
        *,
        command: CreatePerformanceRecalculationBatchCommand,
        selected: ScorePerformanceRecalculationCandidateResult,
        reason_counts: Mapping[RecalculationCandidateReason, int],
        filters: Mapping[str, object],
        target_calculator_name: str,
        target_calculator_version: str,
        target_formula_profile: FormulaProfile,
    ) -> CreatePerformanceRecalculationBatchResult:
        """選択済み candidate から durable batch を作成し、必要なら worker を起動する.

        Args:
            command (CreatePerformanceRecalculationBatchCommand):
                作成 mode、filter、要求時刻を含む command.
            selected (ScorePerformanceRecalculationCandidateResult):
                query repository が選択した候補.
            reason_counts (Mapping[RecalculationCandidateReason, int]):
                candidate reason ごとの件数.
            filters (Mapping[str, object]): 作成 batch に保存する filter snapshot.
            target_calculator_name (str): 対象 calculator の provenance 名.
            target_calculator_version (str): 対象 calculator の provenance version.
            target_formula_profile (FormulaProfile): 対象 playstyle に使う formula profile.

        Returns:
            CreatePerformanceRecalculationBatchResult:
                durable batch、candidate 集計、worker 起動結果.

        Raises:
            ValueError: worker 起動前に作成済み batch の id が割り当てられていない場合.
        """
        work_items = tuple(
            CreateScorePerformanceRecalculationWorkItem(
                score_id=candidate.score_id,
                reason=candidate.reason,
            )
            for candidate in selected.candidates
        )
        async with self._unit_of_work_factory() as uow:
            batch = await uow.score_performance.create_recalculation_batch(
                CreateScorePerformanceRecalculationBatch(
                    filters=filters,
                    reason_counts=reason_counts,
                    target_calculator_version=target_calculator_version,
                    target_formula_profile=target_formula_profile,
                    work_items=work_items,
                    created_at=command.requested_at,
                )
            )
            await uow.commit()

        wake_requested = len(work_items) > 0
        wake_failed = False
        wake_error: str | None = None

        if wake_requested:
            batch_id = batch.id
            if batch_id is None:
                msg = "recalculation batch id must be assigned before worker wake"
                raise ValueError(msg)
            try:
                await self._worker_wake.wake_recalculation_batch(batch_id=batch_id)
            except Exception as exc:
                wake_failed = True
                wake_error = str(exc)

        return CreatePerformanceRecalculationBatchResult(
            outcome=CreatePerformanceRecalculationBatchOutcome.CREATED,
            candidate_count=selected.candidate_count,
            reason_counts=reason_counts,
            filters=filters,
            target_calculator_name=target_calculator_name,
            target_calculator_version=target_calculator_version,
            target_formula_profile=target_formula_profile,
            batch=batch,
            worker_wake_requested=wake_requested,
            worker_wake_failed=wake_failed,
            worker_wake_error=wake_error,
        )


def _validate_optional_positive(field_name: str, value: int | None) -> None:
    """任意の整数 filter が指定時に正であることを検証する.

    Args:
        field_name (str): error message に含める filter 名.
        value (int | None): 検証する値. 未指定時はNone.

    Returns:
        None: 値を検証し、呼び出し側へ値を返さずに完了する.

    Raises:
        ValueError: value が指定されていて0以下の場合.
    """
    if value is not None and value <= 0:
        msg = f"{field_name} must be positive"
        raise ValueError(msg)


def _filters_from_command(
    command: CreatePerformanceRecalculationBatchCommand,
) -> Mapping[str, object]:
    """入力 command の candidate selection 条件を永続化可能な filter snapshot へ変換する.

    Args:
        command (CreatePerformanceRecalculationBatchCommand): filter と安全確認を含む入力 command.

    Returns:
        Mapping[str, object]: query と durable batch で共有する filter 名から値への対応.
    """
    return {
        "score_id": command.score_id,
        "beatmap_id": command.beatmap_id,
        "user_id": command.user_id,
        "ruleset": command.ruleset.name.lower() if command.ruleset is not None else None,
        "limit": command.limit,
        "full_scope": command.full_scope,
        "include_unavailable": command.include_unavailable,
    }


def _requires_full_scope_confirmation(
    command: CreatePerformanceRecalculationBatchCommand,
) -> bool:
    """対象 filter のない execute が明示的な full scope 確認を必要とするか判定する.

    Args:
        command (CreatePerformanceRecalculationBatchCommand):
            mode、filter、確認状態を含む入力 command.

    Returns:
        bool: 危険な全件 execute を拒否すべき場合はTrue.
    """
    return (
        command.mode is CreatePerformanceRecalculationBatchMode.EXECUTE
        and not command.full_scope
        and not _has_narrow_filter(command)
    )


def _has_narrow_filter(command: CreatePerformanceRecalculationBatchCommand) -> bool:
    """入力 command が対象を score、beatmap、user、ruleset のいずれかで絞っているか判定する.

    Args:
        command (CreatePerformanceRecalculationBatchCommand): filter を含む入力 command.

    Returns:
        bool: 少なくとも1つの narrow filter がある場合はTrue.
    """
    return (
        command.score_id is not None
        or command.beatmap_id is not None
        or command.user_id is not None
        or command.ruleset is not None
    )


__all__ = (
    "CreatePerformanceRecalculationBatchCommand",
    "CreatePerformanceRecalculationBatchMode",
    "CreatePerformanceRecalculationBatchOutcome",
    "CreatePerformanceRecalculationBatchResult",
    "CreatePerformanceRecalculationBatchUseCase",
    "NoopPerformanceRecalculationBatchWorkerWake",
    "PerformanceCalculatorIdentity",
    "PerformanceRecalculationBatchWorkerWake",
)
