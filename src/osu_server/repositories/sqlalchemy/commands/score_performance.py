"""SQLAlchemy を用いて score performance calculation と再計算 work を永続化する repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from osu_server.domain.scores.performance import (
    FormulaProfile,
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
    ScorePerformanceCommandConflictError,
)
from osu_server.repositories.sqlalchemy.models.score_performance import (
    PerformanceRecalculationBatchModel,
    PerformanceRecalculationWorkItemModel,
    ScorePerformanceCalculationModel,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

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

_PENDING_STATE_VALUES = tuple(
    state.value for state in PerformanceCalculationState.pending_states()
)


class SQLAlchemyScorePerformanceCommandRepository:
    """UoW 所有の SQLAlchemy session で score performance command state を永続化する repository.

    Attributes:
        _session (AsyncSession): 呼び出し元の Unit of Work が所有する非同期 session.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Work 所有の SQLAlchemy session を保存する.

        Args:
            session (AsyncSession): command transaction を共有する非同期 session.

        Returns:
            None: repository の初期化だけを行い transaction を開始または確定しないことを示す.
        """
        self._session: AsyncSession = session

    async def create_or_reuse_calculation(
        self,
        command: CreateScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationRequestResult:
        """Score の current または pending replacement calculation を作成または再利用する.

        Args:
            command (CreateScorePerformanceCalculation): score ID と calculator request を持つ
                作成要求.

        Returns:
            ScorePerformanceCalculationRequestResult: 作成,再利用,replacement,commit 必要性を
                表す結果.

        Raises:
            ScorePerformanceCommandConflictError: calculation の flush が一意制約などで競合した
                場合.

        Notes:
            異なる pending replacement は superseded にし同じ request の pending replacement は
            再利用する.
        """
        current = await self._get_current_model_for_score(command.score_id)
        if current is None:
            created = ScorePerformanceCalculationModel(
                score_id=command.score_id,
                state=PerformanceCalculationState.QUEUED.value,
                is_current=True,
                pp=None,
                star_rating=None,
                calculator_name=command.calculator_name,
                calculator_version=command.calculator_version,
                formula_profile=command.formula_profile.value,
                beatmap_file_attachment_id=None,
                beatmap_file_checksum_md5=None,
                unavailable_reason=None,
                claim_owner=None,
                claim_expires_at=None,
                attempt_count=0,
                calculated_at=None,
            )
            self._session.add(created)
            await self._flush_or_raise_conflict()
            await self._session.refresh(created)
            return ScorePerformanceCalculationRequestResult(
                calculation=_model_to_domain(created),
                created=True,
                is_replacement=False,
                requires_commit=True,
            )

        if _matches_request(current, command):
            return ScorePerformanceCalculationRequestResult(
                calculation=_model_to_domain(current),
                created=False,
                is_replacement=False,
            )

        replacements = await self._get_pending_replacement_models(command.score_id)
        matching_replacement: ScorePerformanceCalculationModel | None = None
        superseded_replacement = False
        for replacement in replacements:
            if _matches_request(replacement, command):
                matching_replacement = replacement
                continue
            replacement.state = PerformanceCalculationState.SUPERSEDED.value
            replacement.is_current = False
            replacement.claim_owner = None
            replacement.claim_expires_at = None
            superseded_replacement = True

        if superseded_replacement:
            await self._flush_or_raise_conflict()

        if matching_replacement is not None:
            return ScorePerformanceCalculationRequestResult(
                calculation=_model_to_domain(matching_replacement),
                created=False,
                is_replacement=True,
                requires_commit=superseded_replacement,
            )

        created_replacement = ScorePerformanceCalculationModel(
            score_id=command.score_id,
            state=PerformanceCalculationState.QUEUED.value,
            is_current=False,
            pp=None,
            star_rating=None,
            calculator_name=command.calculator_name,
            calculator_version=command.calculator_version,
            formula_profile=command.formula_profile.value,
            beatmap_file_attachment_id=None,
            beatmap_file_checksum_md5=None,
            unavailable_reason=None,
            claim_owner=None,
            claim_expires_at=None,
            attempt_count=0,
            calculated_at=None,
        )
        self._session.add(created_replacement)
        await self._flush_or_raise_conflict()
        await self._session.refresh(created_replacement)
        return ScorePerformanceCalculationRequestResult(
            calculation=_model_to_domain(created_replacement),
            created=True,
            is_replacement=True,
            requires_commit=True,
        )

    async def claim_pending_calculation(
        self,
        command: ClaimScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationClaimResult | None:
        """期限切れまたは未所有の pending calculation を owner に claim する.

        Args:
            command (ClaimScorePerformanceCalculation): calculation ID,owner,claim 時刻と期限を
                持つ要求.

        Returns:
            ScorePerformanceCalculationClaimResult | None: 成功時の claim 結果. 競合または対象外
                なら None.

        Raises:
            ScorePerformanceCommandConflictError: claim の flush が一意制約などで競合した場合.
        """
        model = await self._get_pending_model_for_claim(command.calculation_id)
        if model is None:
            return None
        if model.claim_expires_at is not None and model.claim_expires_at > command.claimed_at:
            return None

        model.claim_owner = command.owner
        model.claim_expires_at = command.claim_expires_at
        model.attempt_count += 1
        await self._flush_or_raise_conflict()
        await self._session.refresh(model)
        claim_owner = model.claim_owner
        claim_expires_at = model.claim_expires_at
        assert claim_owner is not None
        assert claim_expires_at is not None
        return ScorePerformanceCalculationClaimResult(
            calculation=_model_to_domain(model),
            owner=claim_owner,
            expires_at=claim_expires_at,
            attempt_count=model.attempt_count,
        )

    async def mark_completed(
        self,
        command: CompleteScorePerformanceCalculation,
    ) -> PerformanceCalculation | None:
        """Pending calculation を completed にし replacement は current calculation へ昇格する.

        Args:
            command (CompleteScorePerformanceCalculation): performance 値,calculator metadata,
                完了時刻を持つ要求.

        Returns:
            PerformanceCalculation | None: 完了した calculation. 未登録または別 terminal state
                なら None.

        Raises:
            ScorePerformanceCommandConflictError: completion または current replacement の flush が
                競合した場合.

        Notes:
            既に completed の calculation は値を書き換えずそのまま返す.
        """
        model = await self._session.get(ScorePerformanceCalculationModel, command.calculation_id)
        if not isinstance(model, ScorePerformanceCalculationModel):
            return None
        state = PerformanceCalculationState(model.state)
        if not state.is_pending:
            return (
                _model_to_domain(model) if state is PerformanceCalculationState.COMPLETED else None
            )

        model.state = PerformanceCalculationState.COMPLETED.value
        model.pp = command.pp
        model.star_rating = command.star_rating
        model.calculator_name = command.calculator_name
        model.calculator_version = command.calculator_version
        model.formula_profile = command.formula_profile.value
        model.beatmap_file_attachment_id = command.beatmap_file_attachment_id
        model.beatmap_file_checksum_md5 = command.beatmap_file_checksum_md5
        model.unavailable_reason = None
        model.calculated_at = command.calculated_at
        return await self._finalize(model)

    async def update_pending_calculation_state(
        self,
        command: UpdateScorePerformanceCalculationState,
    ) -> PerformanceCalculation | None:
        """Expected state と一致する calculation だけを指定 state へ遷移する.

        Args:
            command (UpdateScorePerformanceCalculationState): calculation ID,expected state,
                遷移先 state を持つ要求.

        Returns:
            PerformanceCalculation | None: 更新後の calculation. expected state が一致しない場合は
                None.

        Raises:
            ScorePerformanceCommandConflictError: state update の flush が一意制約などで競合した
                場合.
        """
        model = (
            await self._session.execute(
                select(ScorePerformanceCalculationModel)
                .where(
                    ScorePerformanceCalculationModel.id == command.calculation_id,
                    ScorePerformanceCalculationModel.state == command.expected_state.value,
                )
                .with_for_update()
                .limit(1)
            )
        ).scalar_one_or_none()
        if not isinstance(model, ScorePerformanceCalculationModel):
            return None

        model.state = command.state.value
        model.updated_at = command.transitioned_at
        await self._flush_or_raise_conflict()
        await self._session.refresh(model)
        return _model_to_domain(model)

    async def mark_unavailable(
        self,
        command: MarkScorePerformanceCalculationUnavailable,
    ) -> PerformanceCalculation | None:
        """Pending calculation を unavailable にして理由と calculator metadata を保存する.

        Args:
            command (MarkScorePerformanceCalculationUnavailable): unavailable 理由,calculator
                metadata,完了時刻を持つ要求.

        Returns:
            PerformanceCalculation | None: unavailable にした calculation. 未登録または別 terminal
                state なら None.

        Raises:
            ScorePerformanceCommandConflictError: unavailable 更新または replacement 昇格の
                flush が競合した場合.

        Notes:
            既に unavailable の calculation は値を書き換えずそのまま返す.
        """
        model = await self._session.get(ScorePerformanceCalculationModel, command.calculation_id)
        if not isinstance(model, ScorePerformanceCalculationModel):
            return None
        state = PerformanceCalculationState(model.state)
        if not state.is_pending:
            return (
                _model_to_domain(model)
                if state is PerformanceCalculationState.UNAVAILABLE
                else None
            )

        model.state = PerformanceCalculationState.UNAVAILABLE.value
        model.pp = None
        model.star_rating = None
        model.calculator_name = command.calculator_name
        model.calculator_version = command.calculator_version
        model.formula_profile = command.formula_profile.value
        model.beatmap_file_attachment_id = command.beatmap_file_attachment_id
        model.beatmap_file_checksum_md5 = command.beatmap_file_checksum_md5
        model.unavailable_reason = command.reason
        model.calculated_at = command.calculated_at
        return await self._finalize(model)

    async def get_by_id(self, calculation_id: int) -> PerformanceCalculation | None:
        """Calculation ID に一致する score performance calculation を返す.

        Args:
            calculation_id (int): 検索する calculation の永続化 ID.

        Returns:
            PerformanceCalculation | None: domain へ変換した calculation. 未登録時は None.
        """
        model = await self._session.get(ScorePerformanceCalculationModel, calculation_id)
        return (
            _model_to_domain(model)
            if isinstance(model, ScorePerformanceCalculationModel)
            else None
        )

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        """Score が現在所有する performance calculation を返す.

        Args:
            score_id (int): current calculation を検索する source score ID.

        Returns:
            PerformanceCalculation | None: is_current が True の calculation. 未登録時は None.
        """
        model = await self._get_current_model_for_score(score_id)
        return _model_to_domain(model) if model is not None else None

    async def create_recalculation_batch(
        self,
        command: CreateScorePerformanceRecalculationBatch,
    ) -> PerformanceRecalculationBatch:
        """再計算 batch と work item を Unit of Work session へ追加する.

        Args:
            command (CreateScorePerformanceRecalculationBatch): batch metadata と型付きの再計算
                候補.

        Returns:
            PerformanceRecalculationBatch: ID が割り当てられた再計算 batch.

        Raises:
            ScorePerformanceCommandConflictError: batch または work item の flush が一意制約などで
                競合した場合.

        Notes:
            work item が空の場合は completed batch を作成する. commit と rollback は呼び出し元が
            所有する.
        """
        status = (
            PerformanceRecalculationBatchStatus.COMPLETED
            if len(command.work_items) == 0
            else PerformanceRecalculationBatchStatus.PENDING
        )
        batch = PerformanceRecalculationBatchModel(
            status=status.value,
            filters=dict(command.filters),
            reason_counts={reason.value: count for reason, count in command.reason_counts.items()},
            target_calculator_version=command.target_calculator_version,
            target_formula_profile=command.target_formula_profile.value,
            candidate_count=len(command.work_items),
            completed_count=0,
            unavailable_count=0,
        )
        batch.created_at = command.created_at
        batch.updated_at = command.created_at
        self._session.add(batch)
        await self._flush_or_raise_conflict()
        await self._session.refresh(batch)

        for work in command.work_items:
            work_item = PerformanceRecalculationWorkItemModel(
                batch_id=batch.id,
                score_id=work.score_id,
                reason=work.reason.value,
                state=PerformanceRecalculationWorkItemState.PENDING.value,
                calculation_id=None,
                claim_owner=None,
                claim_expires_at=None,
                attempt_count=0,
                last_error=None,
            )
            work_item.created_at = command.created_at
            work_item.updated_at = command.created_at
            self._session.add(work_item)

        await self._flush_or_raise_conflict()
        await self._session.refresh(batch)
        return _batch_model_to_domain(batch, last_error=None)

    async def claim_recalculation_work(
        self,
        command: ClaimScorePerformanceRecalculationWork,
    ) -> tuple[PerformanceRecalculationWorkItem, ...]:
        """Claim 可能な再計算 work item を limit 件まで owner に割り当てる.

        Args:
            command (ClaimScorePerformanceRecalculationWork):
                batch ID,owner,claim 期限,最大件数を持つ要求.

        Returns:
            tuple[PerformanceRecalculationWorkItem, ...]: lock を取得して claim した work item.
                対象なしなら空 tuple.

        Raises:
            ValueError: command.limit が 0 以下の場合.
            ScorePerformanceCommandConflictError: claim または batch state の flush が
                一意制約などで競合した場合.

        Notes:
            pending の未所有または期限切れ row と期限切れ claimed row を skip locked で取得する.
        """
        if command.limit <= 0:
            msg = "recalculation work claim limit must be positive"
            raise ValueError(msg)

        models = (
            (
                await self._session.execute(
                    select(PerformanceRecalculationWorkItemModel)
                    .where(
                        PerformanceRecalculationWorkItemModel.batch_id == command.batch_id,
                        or_(
                            and_(
                                PerformanceRecalculationWorkItemModel.state
                                == PerformanceRecalculationWorkItemState.PENDING.value,
                                or_(
                                    PerformanceRecalculationWorkItemModel.claim_expires_at.is_(
                                        None
                                    ),
                                    PerformanceRecalculationWorkItemModel.claim_expires_at
                                    <= command.claimed_at,
                                ),
                            ),
                            and_(
                                PerformanceRecalculationWorkItemModel.state
                                == PerformanceRecalculationWorkItemState.CLAIMED.value,
                                PerformanceRecalculationWorkItemModel.claim_expires_at
                                <= command.claimed_at,
                            ),
                        ),
                    )
                    .order_by(PerformanceRecalculationWorkItemModel.id)
                    .with_for_update(skip_locked=True)
                    .limit(command.limit)
                )
            )
            .scalars()
            .all()
        )
        claimed_models = tuple(models)
        if len(claimed_models) == 0:
            return ()

        for model in claimed_models:
            model.state = PerformanceRecalculationWorkItemState.CLAIMED.value
            model.claim_owner = command.owner
            model.claim_expires_at = command.claim_expires_at
            model.attempt_count += 1
            model.updated_at = command.claimed_at

        batch = await self._session.get(PerformanceRecalculationBatchModel, command.batch_id)
        if isinstance(batch, PerformanceRecalculationBatchModel):
            self._mark_batch_running(batch, command.claimed_at)

        await self._flush_or_raise_conflict()
        for model in claimed_models:
            await self._session.refresh(model)
        return tuple(_work_item_model_to_domain(model) for model in claimed_models)

    async def mark_recalculation_work_completed(
        self,
        command: CompleteScorePerformanceRecalculationWork,
    ) -> PerformanceRecalculationWorkItem | None:
        """Owner が有効に claim した再計算 work item を completed にする.

        Args:
            command (CompleteScorePerformanceRecalculationWork): work item ID,owner,calculation
                ID,完了時刻を持つ要求.

        Returns:
            PerformanceRecalculationWorkItem | None: completed work item. claim が無効なら None.

        Raises:
            ScorePerformanceCommandConflictError: batch progress 更新または work item の flush が
                競合した場合.

        Notes:
            既に completed の row は idempotent に返す. 異なる terminal state は None を返す.
        """
        model = await self._get_claimed_recalculation_work_item_for_update(
            work_item_id=command.work_item_id,
            owner=command.owner,
            at=command.completed_at,
        )
        if model is None:
            existing = await self._session.get(
                PerformanceRecalculationWorkItemModel,
                command.work_item_id,
            )
            if not isinstance(existing, PerformanceRecalculationWorkItemModel):
                return None
            state = PerformanceRecalculationWorkItemState(existing.state)
            return (
                _work_item_model_to_domain(existing)
                if state is PerformanceRecalculationWorkItemState.COMPLETED
                else None
            )

        model.state = PerformanceRecalculationWorkItemState.COMPLETED.value
        model.calculation_id = command.calculation_id
        model.claim_owner = None
        model.claim_expires_at = None
        model.updated_at = command.completed_at
        await self._refresh_batch_progress_from_work_items(
            model.batch_id,
            updated_at=command.completed_at,
        )
        await self._flush_or_raise_conflict()
        await self._session.refresh(model)
        return _work_item_model_to_domain(model)

    async def mark_recalculation_work_unavailable(
        self,
        command: MarkScorePerformanceRecalculationWorkUnavailable,
    ) -> PerformanceRecalculationWorkItem | None:
        """Owner が有効に claim した再計算 work item を unavailable にする.

        Args:
            command (MarkScorePerformanceRecalculationWorkUnavailable): work item ID,owner,理由,
                calculation ID,完了時刻を持つ要求.

        Returns:
            PerformanceRecalculationWorkItem | None: unavailable work item. claim が無効なら None.

        Raises:
            ScorePerformanceCommandConflictError: batch progress 更新または work item の flush が
                競合した場合.

        Notes:
            既に unavailable の row は idempotent に返す. 異なる terminal state は None を返す.
        """
        model = await self._get_claimed_recalculation_work_item_for_update(
            work_item_id=command.work_item_id,
            owner=command.owner,
            at=command.completed_at,
        )
        if model is None:
            existing = await self._session.get(
                PerformanceRecalculationWorkItemModel,
                command.work_item_id,
            )
            if not isinstance(existing, PerformanceRecalculationWorkItemModel):
                return None
            state = PerformanceRecalculationWorkItemState(existing.state)
            return (
                _work_item_model_to_domain(existing)
                if state is PerformanceRecalculationWorkItemState.UNAVAILABLE
                else None
            )

        model.state = PerformanceRecalculationWorkItemState.UNAVAILABLE.value
        model.calculation_id = command.calculation_id
        model.claim_owner = None
        model.claim_expires_at = None
        model.last_error = command.reason
        model.updated_at = command.completed_at
        await self._refresh_batch_progress_from_work_items(
            model.batch_id,
            updated_at=command.completed_at,
        )
        await self._flush_or_raise_conflict()
        await self._session.refresh(model)
        return _work_item_model_to_domain(model)

    async def mark_recalculation_work_failed(
        self,
        command: MarkScorePerformanceRecalculationWorkFailed,
    ) -> PerformanceRecalculationWorkItem | None:
        """Owner が有効に claim した work item の最新 error を記録したまま claim を保持する.

        Args:
            command (MarkScorePerformanceRecalculationWorkFailed): work item ID,owner,error,
                失敗時刻を持つ要求.

        Returns:
            PerformanceRecalculationWorkItem | None: error を更新した claimed work item. claim が
                無効なら None.

        Raises:
            ScorePerformanceCommandConflictError: work item または batch state の flush が競合した
                場合.

        Notes:
            state,claim owner,claim expiry は変更しないため同じ owner が後続の処理を継続できる.
        """
        model = await self._get_claimed_recalculation_work_item_for_update(
            work_item_id=command.work_item_id,
            owner=command.owner,
            at=command.failed_at,
        )
        if model is None:
            return None

        model.last_error = command.error
        model.updated_at = command.failed_at

        batch = await self._session.get(PerformanceRecalculationBatchModel, model.batch_id)
        if isinstance(batch, PerformanceRecalculationBatchModel):
            self._mark_batch_running(batch, command.failed_at)

        await self._flush_or_raise_conflict()
        await self._session.refresh(model)
        return _work_item_model_to_domain(model)

    async def get_recalculation_batch_by_id(
        self,
        batch_id: int,
    ) -> PerformanceRecalculationBatch | None:
        """再計算 batch と最後に記録された work item error を返す.

        Args:
            batch_id (int): 検索する再計算 batch の永続化 ID.

        Returns:
            PerformanceRecalculationBatch | None: reason count と最新 error を復元した batch.
                未登録時は None.
        """
        model = await self._session.get(PerformanceRecalculationBatchModel, batch_id)
        if not isinstance(model, PerformanceRecalculationBatchModel):
            return None
        return _batch_model_to_domain(
            model,
            last_error=await self._latest_recalculation_batch_error(batch_id),
        )

    async def get_recalculation_work_item_by_id(
        self,
        work_item_id: int,
    ) -> PerformanceRecalculationWorkItem | None:
        """再計算 work item ID に一致する domain work item を返す.

        Args:
            work_item_id (int): 検索する再計算 work item の永続化 ID.

        Returns:
            PerformanceRecalculationWorkItem | None: domain へ変換した work item. 未登録時は None.
        """
        model = await self._session.get(PerformanceRecalculationWorkItemModel, work_item_id)
        return (
            _work_item_model_to_domain(model)
            if isinstance(model, PerformanceRecalculationWorkItemModel)
            else None
        )

    async def _get_current_model_for_score(
        self,
        score_id: int,
    ) -> ScorePerformanceCalculationModel | None:
        """Score が current として所有する calculation model を返す.

        Args:
            score_id (int): current calculation を検索する source score ID.

        Returns:
            ScorePerformanceCalculationModel | None: is_current が True の model. 未登録時は None.
        """
        model = (
            await self._session.execute(
                select(ScorePerformanceCalculationModel)
                .where(
                    ScorePerformanceCalculationModel.score_id == score_id,
                    ScorePerformanceCalculationModel.is_current.is_(True),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return model if isinstance(model, ScorePerformanceCalculationModel) else None

    async def _get_pending_replacement_models(
        self,
        score_id: int,
    ) -> tuple[ScorePerformanceCalculationModel, ...]:
        """Score の current ではない pending replacement calculation model を返す.

        Args:
            score_id (int): replacement を検索する source score ID.

        Returns:
            tuple[ScorePerformanceCalculationModel, ...]: pending state の replacement model.
                未登録時は空 tuple.
        """
        models = (
            (
                await self._session.execute(
                    select(ScorePerformanceCalculationModel).where(
                        ScorePerformanceCalculationModel.score_id == score_id,
                        ScorePerformanceCalculationModel.is_current.is_(False),
                        ScorePerformanceCalculationModel.state.in_(_PENDING_STATE_VALUES),
                    )
                )
            )
            .scalars()
            .all()
        )
        return tuple(models)

    async def _get_pending_model_for_claim(
        self,
        calculation_id: int,
    ) -> ScorePerformanceCalculationModel | None:
        """Claim 用に lock を取得できた pending calculation model を返す.

        Args:
            calculation_id (int): claim する calculation の永続化 ID.

        Returns:
            ScorePerformanceCalculationModel | None: skip locked を通過した pending model.
                競合または対象外なら None.
        """
        model = (
            await self._session.execute(
                select(ScorePerformanceCalculationModel)
                .where(
                    ScorePerformanceCalculationModel.id == calculation_id,
                    ScorePerformanceCalculationModel.state.in_(_PENDING_STATE_VALUES),
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        return model if isinstance(model, ScorePerformanceCalculationModel) else None

    async def _get_claimed_recalculation_work_item_for_update(
        self,
        *,
        work_item_id: int,
        owner: str,
        at: datetime,
    ) -> PerformanceRecalculationWorkItemModel | None:
        """Owner と未期限切れ claim が一致する work item を update 用に lock する.

        Args:
            work_item_id (int): lock して更新する work item ID.
            owner (str): claim を現在所有している worker の識別子.
            at (datetime): claim_expires_at より前でなければならない更新時刻.

        Returns:
            PerformanceRecalculationWorkItemModel | None: update lock を取得した claimed model.
                条件不一致なら None.
        """
        model = (
            await self._session.execute(
                select(PerformanceRecalculationWorkItemModel)
                .where(
                    PerformanceRecalculationWorkItemModel.id == work_item_id,
                    PerformanceRecalculationWorkItemModel.state
                    == PerformanceRecalculationWorkItemState.CLAIMED.value,
                    PerformanceRecalculationWorkItemModel.claim_owner == owner,
                    PerformanceRecalculationWorkItemModel.claim_expires_at > at,
                )
                .with_for_update()
                .limit(1)
            )
        ).scalar_one_or_none()
        return model if isinstance(model, PerformanceRecalculationWorkItemModel) else None

    async def _finalize(
        self,
        model: ScorePerformanceCalculationModel,
    ) -> PerformanceCalculation:
        """Terminal calculation の claim を解除し replacement なら current calculation へ昇格する.

        Args:
            model (ScorePerformanceCalculationModel): completed または unavailable として保存する
                calculation model.

        Returns:
            PerformanceCalculation: flush と refresh 後の current status を持つ domain calculation.

        Raises:
            ScorePerformanceCommandConflictError: current calculation の置換または finalize の
                flush が競合した場合.
        """
        model.claim_owner = None
        model.claim_expires_at = None
        if not model.is_current:
            old_current = await self._get_current_model_for_score(model.score_id)
            if old_current is not None and old_current.id != model.id:
                old_current.state = PerformanceCalculationState.SUPERSEDED.value
                old_current.is_current = False
                old_current.claim_owner = None
                old_current.claim_expires_at = None
                await self._flush_or_raise_conflict()
            model.is_current = True

        await self._flush_or_raise_conflict()
        await self._session.refresh(model)
        return _model_to_domain(model)

    async def _refresh_batch_progress_from_work_items(
        self,
        batch_id: int,
        *,
        updated_at: datetime,
    ) -> None:
        """再計算 work item の terminal count から batch progress と status を更新する.

        Args:
            batch_id (int): progress を再集計する再計算 batch ID.
            updated_at (datetime): batch.updated_at に保存する集計時刻.

        Returns:
            None: batch が存在する場合は count と status を session 上で更新したことを示す.

        Raises:
            ScorePerformanceCommandConflictError: 集計前の flush が一意制約などで競合した場合.

        Notes:
            completed と unavailable の合計が candidate_count に一致すると batch は completed
            になる.
        """
        await self._flush_or_raise_conflict()
        batch = (
            await self._session.execute(
                select(PerformanceRecalculationBatchModel)
                .where(PerformanceRecalculationBatchModel.id == batch_id)
                .with_for_update()
                .limit(1)
            )
        ).scalar_one_or_none()
        if not isinstance(batch, PerformanceRecalculationBatchModel):
            return
        work_items = (
            (
                await self._session.execute(
                    select(PerformanceRecalculationWorkItemModel).where(
                        PerformanceRecalculationWorkItemModel.batch_id == batch_id
                    )
                )
            )
            .scalars()
            .all()
        )
        completed_count = sum(
            item.state == PerformanceRecalculationWorkItemState.COMPLETED.value
            for item in work_items
        )
        unavailable_count = sum(
            item.state == PerformanceRecalculationWorkItemState.UNAVAILABLE.value
            for item in work_items
        )
        batch.completed_count = completed_count
        batch.unavailable_count = unavailable_count
        batch.updated_at = updated_at
        terminal_count = batch.completed_count + batch.unavailable_count
        batch.status = (
            PerformanceRecalculationBatchStatus.COMPLETED.value
            if terminal_count == batch.candidate_count
            else PerformanceRecalculationBatchStatus.RUNNING.value
        )

    def _mark_batch_running(
        self,
        batch: PerformanceRecalculationBatchModel,
        updated_at: datetime,
    ) -> None:
        """Completed でない再計算 batch を running に遷移する.

        Args:
            batch (PerformanceRecalculationBatchModel): claim または失敗を記録した batch model.
            updated_at (datetime): batch.updated_at に保存する遷移時刻.

        Returns:
            None: completed batch は保持しそれ以外の batch を running に更新したことを示す.
        """
        if batch.status == PerformanceRecalculationBatchStatus.COMPLETED.value:
            return
        batch.status = PerformanceRecalculationBatchStatus.RUNNING.value
        batch.updated_at = updated_at

    async def _latest_recalculation_batch_error(self, batch_id: int) -> str | None:
        """再計算 batch の work item から最後に更新された error message を返す.

        Args:
            batch_id (int): error を検索する再計算 batch ID.

        Returns:
            str | None: updated_at と ID が最大の non-null error. error がなければ None.
        """
        model = (
            await self._session.execute(
                select(PerformanceRecalculationWorkItemModel)
                .where(
                    PerformanceRecalculationWorkItemModel.batch_id == batch_id,
                    PerformanceRecalculationWorkItemModel.last_error.is_not(None),
                )
                .order_by(
                    PerformanceRecalculationWorkItemModel.updated_at.desc(),
                    PerformanceRecalculationWorkItemModel.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return (
            model.last_error if isinstance(model, PerformanceRecalculationWorkItemModel) else None
        )

    async def _flush_or_raise_conflict(self) -> None:
        """所有 session を flush し IntegrityError を command conflict へ正規化する.

        Returns:
            None: pending SQLAlchemy mutation を database へ送信したことを示す. transaction の
                確定は行わない.

        Raises:
            ScorePerformanceCommandConflictError: database が IntegrityError を送出した場合.
        """
        try:
            await self._session.flush()
        except IntegrityError as exc:
            msg = "score performance command conflict; retry the command"
            raise ScorePerformanceCommandConflictError(msg) from exc


def _matches_request(
    model: ScorePerformanceCalculationModel,
    command: CreateScorePerformanceCalculation,
) -> bool:
    """Calculation model が calculator request と同一の計算条件を持つか判定する.

    Args:
        model (ScorePerformanceCalculationModel): 比較する保存済み calculation model.
        command (CreateScorePerformanceCalculation): calculator name,version,formula profile を
            持つ request.

    Returns:
        bool: 3 つの計算条件がすべて一致する場合は True. それ以外は False.
    """
    return (
        model.calculator_name == command.calculator_name
        and model.calculator_version == command.calculator_version
        and model.formula_profile == command.formula_profile.value
    )


def _model_to_domain(model: ScorePerformanceCalculationModel) -> PerformanceCalculation:
    """SQLAlchemy calculation model を domain performance calculation へ変換する.

    Args:
        model (ScorePerformanceCalculationModel): 永続化済みの score performance calculation model.

    Returns:
        PerformanceCalculation: lifecycle state と formula profile を復元した domain calculation.

    Raises:
        ValueError: 保存済みの calculation state または formula profile が不正な場合.
    """
    return PerformanceCalculation(
        id=model.id,
        score_id=model.score_id,
        state=PerformanceCalculationState(model.state),
        is_current=model.is_current,
        pp=model.pp,
        star_rating=model.star_rating,
        calculator_name=model.calculator_name,
        calculator_version=model.calculator_version,
        formula_profile=FormulaProfile(model.formula_profile),
        beatmap_file_attachment_id=model.beatmap_file_attachment_id,
        beatmap_file_checksum_md5=model.beatmap_file_checksum_md5,
        unavailable_reason=model.unavailable_reason,
        calculated_at=model.calculated_at,
    )


def _batch_model_to_domain(
    model: PerformanceRecalculationBatchModel,
    *,
    last_error: str | None,
) -> PerformanceRecalculationBatch:
    """SQLAlchemy 再計算 batch model を最新 error を含む domain value へ変換する.

    Args:
        model (PerformanceRecalculationBatchModel): 永続化済みの再計算 batch model.
        last_error (str | None): work item から取得した最新 error. error がなければ None.

    Returns:
        PerformanceRecalculationBatch: status,reason count,target formula profile を復元した
            batch.

    Raises:
        TypeError: reason_counts の値が bool を含む int 以外の場合.
        ValueError: 保存済みの batch status,reason,formula profile が不正な場合.
    """
    return PerformanceRecalculationBatch(
        id=model.id,
        status=PerformanceRecalculationBatchStatus(model.status),
        filters=model.filters,
        reason_counts=_reason_counts_to_domain(model),
        target_calculator_version=model.target_calculator_version,
        target_formula_profile=FormulaProfile(model.target_formula_profile),
        candidate_count=model.candidate_count,
        completed_count=model.completed_count,
        unavailable_count=model.unavailable_count,
        last_error=last_error,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _reason_counts_to_domain(
    model: PerformanceRecalculationBatchModel,
) -> dict[RecalculationCandidateReason, int]:
    """保存済み reason count mapping を domain enum key の mapping へ変換する.

    Args:
        model (PerformanceRecalculationBatchModel): reason_counts JSON mapping を持つ再計算 batch
            model.

    Returns:
        dict[RecalculationCandidateReason, int]: domain enum を key にした検証済みの reason count.

    Raises:
        TypeError: reason_counts の値が bool を含む int 以外の場合.
        ValueError: reason_counts の key が定義済みの candidate reason ではない場合.
    """
    reason_counts: dict[RecalculationCandidateReason, int] = {}
    for reason, count in model.reason_counts.items():
        if isinstance(count, bool) or not isinstance(count, int):
            msg = f"batch {model.id} has non-integer reason_counts value for {reason!r}: {count!r}"
            raise TypeError(msg)
        reason_counts[RecalculationCandidateReason(reason)] = count
    return reason_counts


def _work_item_model_to_domain(
    model: PerformanceRecalculationWorkItemModel,
) -> PerformanceRecalculationWorkItem:
    """SQLAlchemy 再計算 work item model を domain value へ変換する.

    Args:
        model (PerformanceRecalculationWorkItemModel): 永続化済みの再計算 work item model.

    Returns:
        PerformanceRecalculationWorkItem: reason,state,claim metadata を復元した domain work
            item.

    Raises:
        ValueError: 保存済みの candidate reason または work item state が不正な場合.
    """
    return PerformanceRecalculationWorkItem(
        id=model.id,
        batch_id=model.batch_id,
        score_id=model.score_id,
        reason=RecalculationCandidateReason(model.reason),
        state=PerformanceRecalculationWorkItemState(model.state),
        calculation_id=model.calculation_id,
        claim_owner=model.claim_owner,
        claim_expires_at=model.claim_expires_at,
        attempt_count=model.attempt_count,
        last_error=model.last_error,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
