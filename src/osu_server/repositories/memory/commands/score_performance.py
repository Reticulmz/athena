"""In-memory command 側 score performance repository を実装する module."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.domain.scores.performance import (
    PerformanceCalculation,
    PerformanceCalculationState,
    PerformanceRecalculationBatch,
    PerformanceRecalculationBatchStatus,
    PerformanceRecalculationWorkItem,
    PerformanceRecalculationWorkItemState,
    RecalculationCandidateReason,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    ScorePerformanceCalculationClaimResult,
    ScorePerformanceCalculationRequestResult,
)
from osu_server.repositories.memory.commands.state import (
    InMemoryPerformanceClaim,
    InMemoryPerformanceRecalculationBatchRecord,
    InMemoryPerformanceRecalculationWorkItemRecord,
)

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.repositories.interfaces.commands.score_performance import (
        ClaimScorePerformanceCalculation,
        ClaimScorePerformanceRecalculationWork,
        CompleteScorePerformanceCalculation,
        CompleteScorePerformanceRecalculationWork,
        CreateScorePerformanceCalculation,
        CreateScorePerformanceRecalculationBatch,
        MarkScorePerformanceCalculationUnavailable,
        MarkScorePerformanceRecalculationWorkFailed,
        MarkScorePerformanceRecalculationWorkUnavailable,
        UpdateScorePerformanceCalculationState,
    )
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryScorePerformanceCommandRepository:
    """Score performance calculation と recalculation work の state transition を管理する.

    Attributes:
        _state (InMemoryCommandRepositoryState): 所有 Unit of Work の可変 state snapshot.

    Notes:
        この repository は lock 又は thread synchronization を提供しない. 同じ state を
        複数 task 又は thread から同時に変更してはならない. claim はこの state snapshot 内の
        lease metadata であり, cross-process mutual exclusion を提供しない.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """Active Unit of Work の state snapshot を保持する.

        Args:
            state (InMemoryCommandRepositoryState): repository が直接読み書きする state.

        Returns:
            None: state への参照を保持したことを示す.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def create_or_reuse_calculation(
        self,
        command: CreateScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationRequestResult:
        """Score の current 又は replacement calculation を作成又は再利用する.

        Args:
            command (CreateScorePerformanceCalculation): score ID と calculator request metadata.

        Returns:
            ScorePerformanceCalculationRequestResult: request に対応する calculation と作成結果.

        Notes:
            current calculation がなければ current queued row を作成する. current 又は replacement
            が request metadata と一致すればその row を再利用する. 異なる replacement があれば
            それを SUPERSEDED にしてから新しい replacement queued row を作成する.
        """
        current = await self.get_current_for_score(command.score_id)
        if current is None:
            return self._create_calculation(command, is_current=True, is_replacement=False)
        if _matches_request(current, command):
            return ScorePerformanceCalculationRequestResult(
                calculation=current,
                created=False,
                is_replacement=False,
            )

        replacement = self._get_replacement_for_score(command.score_id)
        if replacement is not None and _matches_request(replacement, command):
            return ScorePerformanceCalculationRequestResult(
                calculation=replacement,
                created=False,
                is_replacement=True,
            )

        if replacement is not None:
            self._state.performance_calculations_by_id[replacement.id or 0] = replace(
                replacement,
                state=PerformanceCalculationState.SUPERSEDED,
                is_current=False,
            )
        return self._create_calculation(command, is_current=False, is_replacement=True)

    async def claim_pending_calculation(
        self,
        command: ClaimScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationClaimResult | None:
        """Pending calculation の lease を取得できる場合だけ claim を保存する.

        Args:
            command (ClaimScorePerformanceCalculation): calculation ID, owner, claim 時刻と期限.

        Returns:
            ScorePerformanceCalculationClaimResult | None:
                新規又は期限切れ claim の結果. calculation がない, pending でない, 又は有効な
                claim が残る場合は None.

        Notes:
            expires_at が claimed_at と等しい claim は期限切れとして再取得できる. 再取得では
            既存 attempt_count を 1 増やす.
        """
        calculation = self._state.performance_calculations_by_id.get(command.calculation_id)
        if calculation is None or not calculation.state.is_pending:
            return None

        existing_claim = self._state.performance_claims_by_calculation_id.get(
            command.calculation_id
        )
        if existing_claim is not None and existing_claim.expires_at > command.claimed_at:
            return None

        attempt_count = 1 if existing_claim is None else existing_claim.attempt_count + 1
        claim = InMemoryPerformanceClaim(
            owner=command.owner,
            expires_at=command.claim_expires_at,
            attempt_count=attempt_count,
        )
        self._state.performance_claims_by_calculation_id[command.calculation_id] = claim
        return ScorePerformanceCalculationClaimResult(
            calculation=calculation,
            owner=claim.owner,
            expires_at=claim.expires_at,
            attempt_count=claim.attempt_count,
        )

    async def mark_completed(
        self,
        command: CompleteScorePerformanceCalculation,
    ) -> PerformanceCalculation | None:
        """Pending calculation を completed にして current calculation として確定する.

        Args:
            command (CompleteScorePerformanceCalculation): 完了した calculation の output metadata.

        Returns:
            PerformanceCalculation | None: 完了後の calculation. 未登録, completed 以外の terminal
            state, 又は pending 以外の state なら None. すでに completed なら既存 row を返す.

        Raises:
            ValueError: state の calculation が repository ID を持たず finalize できない場合.

        Notes:
            pending row では claim owner を検証しない. replacement を確定すると旧 current row を
            SUPERSEDED にして current index を更新し, calculation claim を削除する.
        """
        calculation = self._state.performance_calculations_by_id.get(command.calculation_id)
        if calculation is None:
            return None
        if not calculation.state.is_pending:
            return (
                calculation if calculation.state is PerformanceCalculationState.COMPLETED else None
            )

        completed = replace(
            calculation,
            state=PerformanceCalculationState.COMPLETED,
            pp=command.pp,
            star_rating=command.star_rating,
            calculator_name=command.calculator_name,
            calculator_version=command.calculator_version,
            formula_profile=command.formula_profile,
            beatmap_file_attachment_id=command.beatmap_file_attachment_id,
            beatmap_file_checksum_md5=command.beatmap_file_checksum_md5,
            unavailable_reason=None,
            calculated_at=command.calculated_at,
        )
        return self._finalize(completed)

    async def update_pending_calculation_state(
        self,
        command: UpdateScorePerformanceCalculationState,
    ) -> PerformanceCalculation | None:
        """Expected pending state が一致する calculation だけ state を置き換える.

        Args:
            command (UpdateScorePerformanceCalculationState):
                calculation ID, expected state, target state.

        Returns:
            PerformanceCalculation | None: state を更新した calculation. 未登録, pending 以外,
            又は expected state 不一致なら None.

        Notes:
            state だけを更新する. current index と claim metadata は変更しない.
        """
        calculation = self._state.performance_calculations_by_id.get(command.calculation_id)
        if calculation is None or not calculation.state.is_pending:
            return None
        if calculation.state is not command.expected_state:
            return None

        updated = replace(calculation, state=command.state)
        self._state.performance_calculations_by_id[command.calculation_id] = updated
        return updated

    async def mark_unavailable(
        self,
        command: MarkScorePerformanceCalculationUnavailable,
    ) -> PerformanceCalculation | None:
        """Pending calculation を unavailable にして current calculation として確定する.

        Args:
            command (MarkScorePerformanceCalculationUnavailable):
                unavailable result metadata と理由.

        Returns:
            PerformanceCalculation | None: unavailable 後の calculation. 未登録, unavailable 以外の
            terminal state, 又は pending 以外なら None. すでに unavailable なら既存 row を返す.

        Raises:
            ValueError: state の calculation が repository ID を持たず finalize できない場合.

        Notes:
            pending row では claim owner を検証しない. pp と star_rating を None にし,
            calculation claim を削除して current index を必要に応じて置き換える.
        """
        calculation = self._state.performance_calculations_by_id.get(command.calculation_id)
        if calculation is None:
            return None
        if not calculation.state.is_pending:
            return (
                calculation
                if calculation.state is PerformanceCalculationState.UNAVAILABLE
                else None
            )

        unavailable = replace(
            calculation,
            state=PerformanceCalculationState.UNAVAILABLE,
            pp=None,
            star_rating=None,
            calculator_name=command.calculator_name,
            calculator_version=command.calculator_version,
            formula_profile=command.formula_profile,
            beatmap_file_attachment_id=command.beatmap_file_attachment_id,
            beatmap_file_checksum_md5=command.beatmap_file_checksum_md5,
            unavailable_reason=command.reason,
            calculated_at=command.calculated_at,
        )
        return self._finalize(unavailable)

    async def get_by_id(self, calculation_id: int) -> PerformanceCalculation | None:
        """Calculation ID から保存済み performance calculation を返す.

        Args:
            calculation_id (int): 検索する calculation の識別子.

        Returns:
            PerformanceCalculation | None: 保存済み calculation. 未登録なら None.
        """
        return self._state.performance_calculations_by_id.get(calculation_id)

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        """Score の current performance calculation を返す.

        Args:
            score_id (int): current calculation を検索する score の識別子.

        Returns:
            PerformanceCalculation | None: current index と主記録が存在する calculation. 未登録又は
            不整合時は None.
        """
        current_id = self._state.current_performance_calculation_id_by_score_id.get(score_id)
        if current_id is None:
            return None
        return self._state.performance_calculations_by_id.get(current_id)

    async def create_recalculation_batch(
        self,
        command: CreateScorePerformanceRecalculationBatch,
    ) -> PerformanceRecalculationBatch:
        """Recalculation batch と work items を in-memory state に追加する.

        Args:
            command (CreateScorePerformanceRecalculationBatch): batch metadata と型付き candidates.

        Returns:
            PerformanceRecalculationBatch: ID が割り当てられた再計算 batch.

        Notes:
            空の work_items は COMPLETED batch を作成する. それ以外は PENDING batch と各 candidate
            に PENDING work item を作成する. Enum は persistence representation と同じ value
            文字列で保存し, input filters と reason_counts は新しい dict に copy する.
        """
        batch_id = self._state.next_performance_recalculation_batch_id
        self._state.next_performance_recalculation_batch_id += 1
        batch_status = (
            PerformanceRecalculationBatchStatus.COMPLETED
            if len(command.work_items) == 0
            else PerformanceRecalculationBatchStatus.PENDING
        )
        batch = InMemoryPerformanceRecalculationBatchRecord(
            id=batch_id,
            status=batch_status.value,
            filters=dict(command.filters),
            reason_counts={reason.value: count for reason, count in command.reason_counts.items()},
            target_calculator_version=command.target_calculator_version,
            target_formula_profile=command.target_formula_profile,
            candidate_count=len(command.work_items),
            completed_count=0,
            unavailable_count=0,
            created_at=command.created_at,
            updated_at=command.created_at,
        )
        self._state.performance_recalculation_batches_by_id[batch_id] = batch
        self._state.performance_recalculation_work_item_ids_by_batch_id[batch_id] = []

        for work in command.work_items:
            work_item_id = self._state.next_performance_recalculation_work_item_id
            self._state.next_performance_recalculation_work_item_id += 1
            work_item = InMemoryPerformanceRecalculationWorkItemRecord(
                id=work_item_id,
                batch_id=batch_id,
                score_id=work.score_id,
                reason=work.reason.value,
                state=PerformanceRecalculationWorkItemState.PENDING.value,
                calculation_id=None,
                claim=None,
                attempt_count=0,
                last_error=None,
                created_at=command.created_at,
                updated_at=command.created_at,
            )
            self._state.performance_recalculation_work_items_by_id[work_item_id] = work_item
            self._state.performance_recalculation_work_item_ids_by_batch_id[batch_id].append(
                work_item_id
            )

        return self._batch_to_domain(batch)

    async def claim_recalculation_work(
        self,
        command: ClaimScorePerformanceRecalculationWork,
    ) -> tuple[PerformanceRecalculationWorkItem, ...]:
        """Batch 内の claimable work items を上限まで claim する.

        Args:
            command (ClaimScorePerformanceRecalculationWork):
                batch ID, owner, limit, claim lease metadata.

        Returns:
            tuple[PerformanceRecalculationWorkItem, ...]:
                claim に成功した insertion-order work items. batch がないか claimable item が
                なければ空 tuple.

        Raises:
            ValueError: command.limit が 0 以下, 又は保存 work item の state が未知の Enum value の
                場合.

        Notes:
            PENDING 又は有効期限内 claim を持たない CLAIMED item だけを claim する. 各 item は
            CLAIMED に遷移し, attempt_count を増やす. 一件以上 claim すると batch を RUNNING に
            更新する.
        """
        if command.limit <= 0:
            msg = "recalculation work claim limit must be positive"
            raise ValueError(msg)

        batch = self._state.performance_recalculation_batches_by_id.get(command.batch_id)
        if batch is None:
            return ()

        claimable = [
            item
            for item in self._work_items_for_batch(command.batch_id)
            if _is_recalculation_work_claimable(item, command.claimed_at)
        ][: command.limit]
        if len(claimable) == 0:
            return ()

        claimed_items: list[PerformanceRecalculationWorkItem] = []
        for item in claimable:
            attempt_count = item.attempt_count + 1
            claim = InMemoryPerformanceClaim(
                owner=command.owner,
                expires_at=command.claim_expires_at,
                attempt_count=attempt_count,
            )
            claimed = replace(
                item,
                state=PerformanceRecalculationWorkItemState.CLAIMED.value,
                claim=claim,
                attempt_count=attempt_count,
                updated_at=command.claimed_at,
            )
            self._state.performance_recalculation_work_items_by_id[item.id] = claimed
            claimed_items.append(_work_item_to_domain(claimed))

        self._set_batch_running(command.batch_id, command.claimed_at)
        return tuple(claimed_items)

    async def mark_recalculation_work_completed(
        self,
        command: CompleteScorePerformanceRecalculationWork,
    ) -> PerformanceRecalculationWorkItem | None:
        """有効な owner claim を持つ work item を completed に遷移する.

        Args:
            command (CompleteScorePerformanceRecalculationWork):
                work item ID, owner, calculation ID, 完了時刻.

        Returns:
            PerformanceRecalculationWorkItem | None: completed item. 未登録, 他 terminal state,
            又は有効な owner claim がない場合は None. すでに completed なら既存 item を返す.

        Raises:
            ValueError: state に保存した work item state が未知の Enum value の場合.

        Notes:
            成功時は calculation ID を設定して claim を除去し, batch progress と batch status を
            更新する.
        """
        item = self._state.performance_recalculation_work_items_by_id.get(command.work_item_id)
        if item is None:
            return None
        state = PerformanceRecalculationWorkItemState(item.state)
        if state.is_terminal:
            return (
                _work_item_to_domain(item)
                if state is PerformanceRecalculationWorkItemState.COMPLETED
                else None
            )
        if not _has_active_recalculation_work_claim(
            item,
            owner=command.owner,
            at=command.completed_at,
        ):
            return None

        completed = replace(
            item,
            state=PerformanceRecalculationWorkItemState.COMPLETED.value,
            calculation_id=command.calculation_id,
            claim=None,
            updated_at=command.completed_at,
        )
        self._state.performance_recalculation_work_items_by_id[item.id] = completed
        self._refresh_batch_progress(item.batch_id, command.completed_at)
        return _work_item_to_domain(completed)

    async def mark_recalculation_work_unavailable(
        self,
        command: MarkScorePerformanceRecalculationWorkUnavailable,
    ) -> PerformanceRecalculationWorkItem | None:
        """有効な owner claim を持つ work item を unavailable に遷移する.

        Args:
            command (MarkScorePerformanceRecalculationWorkUnavailable):
                work item ID, owner, calculation ID, unavailable 理由, 完了時刻.

        Returns:
            PerformanceRecalculationWorkItem | None: unavailable item. 未登録, 他 terminal state,
            又は有効な owner claim がない場合は None. すでに unavailable なら既存 item を返す.

        Raises:
            ValueError: state に保存した work item state が未知の Enum value の場合.

        Notes:
            成功時は calculation ID と last_error を設定して claim を除去し, batch progress と
            batch status を更新する.
        """
        item = self._state.performance_recalculation_work_items_by_id.get(command.work_item_id)
        if item is None:
            return None
        state = PerformanceRecalculationWorkItemState(item.state)
        if state.is_terminal:
            return (
                _work_item_to_domain(item)
                if state is PerformanceRecalculationWorkItemState.UNAVAILABLE
                else None
            )
        if not _has_active_recalculation_work_claim(
            item,
            owner=command.owner,
            at=command.completed_at,
        ):
            return None

        unavailable = replace(
            item,
            state=PerformanceRecalculationWorkItemState.UNAVAILABLE.value,
            calculation_id=command.calculation_id,
            claim=None,
            last_error=command.reason,
            updated_at=command.completed_at,
        )
        self._state.performance_recalculation_work_items_by_id[item.id] = unavailable
        self._refresh_batch_progress(item.batch_id, command.completed_at)
        return _work_item_to_domain(unavailable)

    async def mark_recalculation_work_failed(
        self,
        command: MarkScorePerformanceRecalculationWorkFailed,
    ) -> PerformanceRecalculationWorkItem | None:
        """有効な owner claim を持つ work item の最後の error を更新する.

        Args:
            command (MarkScorePerformanceRecalculationWorkFailed):
                work item ID, owner, error, failure 時刻.

        Returns:
            PerformanceRecalculationWorkItem | None:
                error を更新した claimed item. 未登録, terminal, 又は有効な owner claim が
                ない場合は None.

        Raises:
            ValueError: state に保存した work item state が未知の Enum value の場合.

        Notes:
            成功時も item state と claim は保持する. batch は RUNNING に更新する.
        """
        item = self._state.performance_recalculation_work_items_by_id.get(command.work_item_id)
        if item is None:
            return None
        if PerformanceRecalculationWorkItemState(item.state).is_terminal:
            return None
        if not _has_active_recalculation_work_claim(
            item,
            owner=command.owner,
            at=command.failed_at,
        ):
            return None

        failed = replace(
            item,
            last_error=command.error,
            updated_at=command.failed_at,
        )
        self._state.performance_recalculation_work_items_by_id[item.id] = failed
        self._set_batch_running(item.batch_id, command.failed_at)
        return _work_item_to_domain(failed)

    async def get_recalculation_batch_by_id(
        self,
        batch_id: int,
    ) -> PerformanceRecalculationBatch | None:
        """Recalculation batch ID から domain batch を再構築して返す.

        Args:
            batch_id (int): 検索する recalculation batch の識別子.

        Returns:
            PerformanceRecalculationBatch | None: 保存 record から変換した batch. 未登録なら None.

        Raises:
            ValueError: 保存 record の batch status 又は reason が未知の Enum value の場合.
        """
        batch = self._state.performance_recalculation_batches_by_id.get(batch_id)
        return self._batch_to_domain(batch) if batch is not None else None

    async def get_recalculation_work_item_by_id(
        self,
        work_item_id: int,
    ) -> PerformanceRecalculationWorkItem | None:
        """Recalculation work item ID から domain work item を再構築して返す.

        Args:
            work_item_id (int): 検索する recalculation work item の識別子.

        Returns:
            PerformanceRecalculationWorkItem | None:
                保存 record から変換した work item. 未登録なら None.

        Raises:
            ValueError: 保存 record の reason 又は state が未知の Enum value の場合.
        """
        item = self._state.performance_recalculation_work_items_by_id.get(work_item_id)
        return _work_item_to_domain(item) if item is not None else None

    def _create_calculation(
        self,
        command: CreateScorePerformanceCalculation,
        *,
        is_current: bool,
        is_replacement: bool,
    ) -> ScorePerformanceCalculationRequestResult:
        """Queued performance calculation を作成し必要な score index を更新する.

        Args:
            command (CreateScorePerformanceCalculation): score ID と calculator request metadata.
            is_current (bool): 新規 calculation を current index に登録するか.
            is_replacement (bool): 新規 calculation を replacement index に登録するか.

        Returns:
            ScorePerformanceCalculationRequestResult:
                created=True, requires_commit=True の新規 request result.

        Notes:
            next_performance_calculation_id を増やして QUEUED row を保存する. is_current と
            is_replacement の各 flag に対応する index だけを更新する.
        """
        calculation_id = self._state.next_performance_calculation_id
        self._state.next_performance_calculation_id += 1
        calculation = PerformanceCalculation(
            id=calculation_id,
            score_id=command.score_id,
            state=PerformanceCalculationState.QUEUED,
            is_current=is_current,
            pp=None,
            star_rating=None,
            calculator_name=command.calculator_name,
            calculator_version=command.calculator_version,
            formula_profile=command.formula_profile,
            beatmap_file_attachment_id=None,
            beatmap_file_checksum_md5=None,
            unavailable_reason=None,
            calculated_at=None,
        )
        self._state.performance_calculations_by_id[calculation_id] = calculation
        if is_current:
            self._state.current_performance_calculation_id_by_score_id[command.score_id] = (
                calculation_id
            )
        if is_replacement:
            self._state.replacement_performance_calculation_id_by_score_id[command.score_id] = (
                calculation_id
            )
        return ScorePerformanceCalculationRequestResult(
            calculation=calculation,
            created=True,
            is_replacement=is_replacement,
            requires_commit=True,
        )

    def _get_replacement_for_score(self, score_id: int) -> PerformanceCalculation | None:
        """Score の replacement calculation を replacement index から取得する.

        Args:
            score_id (int): replacement calculation を検索する score の識別子.

        Returns:
            PerformanceCalculation | None: index と主記録が存在する replacement calculation.
            replacement index がないか不整合なら None.
        """
        replacement_id = self._state.replacement_performance_calculation_id_by_score_id.get(
            score_id
        )
        if replacement_id is None:
            return None
        return self._state.performance_calculations_by_id.get(replacement_id)

    def _finalize(self, calculation: PerformanceCalculation) -> PerformanceCalculation:
        """Terminal calculation を保存し current index と claim を整合させる.

        Args:
            calculation (PerformanceCalculation):
                COMPLETED 又は UNAVAILABLE として確定する calculation.

        Returns:
            PerformanceCalculation: current flag と indexes を反映して保存した calculation.

        Raises:
            ValueError: calculation.id が None で repository identity を取得できない場合.

        Notes:
            calculation が replacement の場合は旧 current calculation を SUPERSEDED にし, 新しい
            calculation を current に昇格して replacement index を削除する. 常に calculation の
            claim を削除する.
        """
        calculation_id = _require_calculation_id(calculation)
        if not calculation.is_current:
            old_current_id = self._state.current_performance_calculation_id_by_score_id.get(
                calculation.score_id
            )
            if old_current_id is not None and old_current_id != calculation_id:
                old_current = self._state.performance_calculations_by_id.get(old_current_id)
                if old_current is not None:
                    self._state.performance_calculations_by_id[old_current_id] = replace(
                        old_current,
                        state=PerformanceCalculationState.SUPERSEDED,
                        is_current=False,
                    )
            calculation = replace(calculation, is_current=True)
            self._state.current_performance_calculation_id_by_score_id[calculation.score_id] = (
                calculation_id
            )
            _ = self._state.replacement_performance_calculation_id_by_score_id.pop(
                calculation.score_id,
                None,
            )

        self._state.performance_calculations_by_id[calculation_id] = calculation
        _ = self._state.performance_claims_by_calculation_id.pop(calculation_id, None)
        return calculation

    def _work_items_for_batch(
        self,
        batch_id: int,
    ) -> tuple[InMemoryPerformanceRecalculationWorkItemRecord, ...]:
        """Batch の insertion-order index から現存する work item records を返す.

        Args:
            batch_id (int): work items を取得する recalculation batch の識別子.

        Returns:
            tuple[InMemoryPerformanceRecalculationWorkItemRecord, ...]: index 順の現存 records.

        Notes:
            batch index がないか参照先 record が欠落している場合は該当 item を結果から除外する.
        """
        item_ids = self._state.performance_recalculation_work_item_ids_by_batch_id.get(
            batch_id,
            [],
        )
        return tuple(
            item
            for item_id in item_ids
            if (item := self._state.performance_recalculation_work_items_by_id.get(item_id))
            is not None
        )

    def _set_batch_running(self, batch_id: int, updated_at: datetime) -> None:
        """Completed でない既存 batch を RUNNING に遷移する.

        Args:
            batch_id (int): 更新する recalculation batch の識別子.
            updated_at (datetime): batch.updated_at に保存する timestamp.

        Returns:
            None: 対象 batch を RUNNING に更新したことを示す.

        Notes:
            batch が未登録又はすでに COMPLETED の場合は state を変更しない.
        """
        batch = self._state.performance_recalculation_batches_by_id.get(batch_id)
        if batch is None or batch.status == PerformanceRecalculationBatchStatus.COMPLETED.value:
            return
        self._state.performance_recalculation_batches_by_id[batch_id] = replace(
            batch,
            status=PerformanceRecalculationBatchStatus.RUNNING.value,
            updated_at=updated_at,
        )

    def _refresh_batch_progress(self, batch_id: int, updated_at: datetime) -> None:
        """Batch の terminal work item 数と status を再集計して保存する.

        Args:
            batch_id (int): 再集計する recalculation batch の識別子.
            updated_at (datetime): batch.updated_at に保存する timestamp.

        Returns:
            None: batch が存在する場合に progress と status を保存したことを示す.

        Notes:
            COMPLETED と UNAVAILABLE の数を別々に数える. 両者の合計が candidate_count に等しい
            場合は COMPLETED, それ以外は RUNNING とする. batch が未登録なら state を変更しない.
        """
        batch = self._state.performance_recalculation_batches_by_id.get(batch_id)
        if batch is None:
            return
        work_items = self._work_items_for_batch(batch_id)
        completed_count = sum(
            item.state == PerformanceRecalculationWorkItemState.COMPLETED.value
            for item in work_items
        )
        unavailable_count = sum(
            item.state == PerformanceRecalculationWorkItemState.UNAVAILABLE.value
            for item in work_items
        )
        terminal_count = completed_count + unavailable_count
        status = (
            PerformanceRecalculationBatchStatus.COMPLETED
            if terminal_count == batch.candidate_count
            else PerformanceRecalculationBatchStatus.RUNNING
        )
        self._state.performance_recalculation_batches_by_id[batch_id] = replace(
            batch,
            status=status.value,
            completed_count=completed_count,
            unavailable_count=unavailable_count,
            updated_at=updated_at,
        )

    def _batch_to_domain(
        self,
        batch: InMemoryPerformanceRecalculationBatchRecord,
    ) -> PerformanceRecalculationBatch:
        """In-memory batch record を public domain batch へ変換する.

        Args:
            batch (InMemoryPerformanceRecalculationBatchRecord): 変換する保存済み batch record.

        Returns:
            PerformanceRecalculationBatch: Enum value を domain Enum に復元した batch.

        Raises:
            ValueError: batch.status 又は reason_counts の key が未知の Enum value の場合.

        Notes:
            last_error は work items のうち updated_at と ID が最大の error を使用する.
        """
        return PerformanceRecalculationBatch(
            id=batch.id,
            status=PerformanceRecalculationBatchStatus(batch.status),
            filters=batch.filters,
            reason_counts={
                RecalculationCandidateReason(reason): count
                for reason, count in batch.reason_counts.items()
            },
            target_calculator_version=batch.target_calculator_version,
            target_formula_profile=batch.target_formula_profile,
            candidate_count=batch.candidate_count,
            completed_count=batch.completed_count,
            unavailable_count=batch.unavailable_count,
            last_error=self._latest_batch_error(batch.id),
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )

    def _latest_batch_error(self, batch_id: int) -> str | None:
        """Batch 内で最後に更新された non-None error を返す.

        Args:
            batch_id (int): work item errors を検索する recalculation batch の識別子.

        Returns:
            str | None: updated_at, ID が最大の work item の last_error. error がなければ None.
        """
        work_items_with_errors = [
            item for item in self._work_items_for_batch(batch_id) if item.last_error is not None
        ]
        if len(work_items_with_errors) == 0:
            return None
        return max(work_items_with_errors, key=lambda item: (item.updated_at, item.id)).last_error


def _matches_request(
    calculation: PerformanceCalculation,
    command: CreateScorePerformanceCalculation,
) -> bool:
    """Calculation が create request の calculator metadata と一致するか判定する.

    Args:
        calculation (PerformanceCalculation): 比較する保存済み calculation.
        command (CreateScorePerformanceCalculation): 比較する create request.

    Returns:
        bool: calculator name, version, formula profile がすべて一致する場合は True.
    """
    return (
        calculation.calculator_name == command.calculator_name
        and calculation.calculator_version == command.calculator_version
        and calculation.formula_profile is command.formula_profile
    )


def _require_calculation_id(calculation: PerformanceCalculation) -> int:
    """Performance calculation の repository identity を必須として取得する.

    Args:
        calculation (PerformanceCalculation): identity を取得する calculation.

    Returns:
        int: non-None calculation ID.

    Raises:
        ValueError: calculation.id が None の場合.
    """
    if calculation.id is None:
        msg = "performance calculation must have repository identity"
        raise ValueError(msg)
    return calculation.id


def _is_recalculation_work_claimable(
    item: InMemoryPerformanceRecalculationWorkItemRecord,
    claimed_at: datetime,
) -> bool:
    """Work item が指定時刻に claim 可能か判定する.

    Args:
        item (InMemoryPerformanceRecalculationWorkItemRecord): 判定する保存済み work item.
        claimed_at (datetime): 現在の claim 時刻として比較する timestamp.

    Returns:
        bool: PENDING, 又は有効期限内 claim を持たない CLAIMED item の場合は True.

    Raises:
        ValueError: item.state が未知の PerformanceRecalculationWorkItemState value の場合.
    """
    state = PerformanceRecalculationWorkItemState(item.state)
    if state.is_terminal:
        return False
    if item.claim is not None and item.claim.expires_at > claimed_at:
        return False
    return state in {
        PerformanceRecalculationWorkItemState.PENDING,
        PerformanceRecalculationWorkItemState.CLAIMED,
    }


def _has_active_recalculation_work_claim(
    item: InMemoryPerformanceRecalculationWorkItemRecord,
    *,
    owner: str,
    at: datetime,
) -> bool:
    """Work item に指定 owner の有効な claim があるか判定する.

    Args:
        item (InMemoryPerformanceRecalculationWorkItemRecord): claim を調べる work item.
        owner (str): 完了又は失敗操作を行う worker の識別子.
        at (datetime): claim expiry と比較する操作時刻.

    Returns:
        bool: item が CLAIMED で claim owner が一致し, expires_at が at より後なら True.
    """
    return (
        item.state == PerformanceRecalculationWorkItemState.CLAIMED.value
        and item.claim is not None
        and item.claim.owner == owner
        and item.claim.expires_at > at
    )


def _work_item_to_domain(
    item: InMemoryPerformanceRecalculationWorkItemRecord,
) -> PerformanceRecalculationWorkItem:
    """In-memory work item record を public domain work item へ変換する.

    Args:
        item (InMemoryPerformanceRecalculationWorkItemRecord): 変換する保存済み work item record.

    Returns:
        PerformanceRecalculationWorkItem: claim metadata を public fields に展開した work item.

    Raises:
        ValueError: item.reason 又は item.state が未知の Enum value の場合.
    """
    claim_owner = None if item.claim is None else item.claim.owner
    claim_expires_at = None if item.claim is None else item.claim.expires_at
    return PerformanceRecalculationWorkItem(
        id=item.id,
        batch_id=item.batch_id,
        score_id=item.score_id,
        reason=RecalculationCandidateReason(item.reason),
        state=PerformanceRecalculationWorkItemState(item.state),
        calculation_id=item.calculation_id,
        claim_owner=claim_owner,
        claim_expires_at=claim_expires_at,
        attempt_count=item.attempt_count,
        last_error=item.last_error,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
