"""SQLAlchemy command-side score performance repository."""

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
    """Score performance command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def create_or_reuse_calculation(
        self,
        command: CreateScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationRequestResult:
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
        model = await self._session.get(ScorePerformanceCalculationModel, calculation_id)
        return (
            _model_to_domain(model)
            if isinstance(model, ScorePerformanceCalculationModel)
            else None
        )

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        model = await self._get_current_model_for_score(score_id)
        return _model_to_domain(model) if model is not None else None

    async def create_recalculation_batch(
        self,
        command: CreateScorePerformanceRecalculationBatch,
    ) -> PerformanceRecalculationBatch:
        status = (
            PerformanceRecalculationBatchStatus.COMPLETED
            if len(command.work_items) == 0
            else PerformanceRecalculationBatchStatus.PENDING
        )
        batch = PerformanceRecalculationBatchModel(
            status=status.value,
            filters=dict(command.filters),
            reason_counts=dict(command.reason_counts),
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
                reason=work.reason,
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
        if not model.is_current:
            old_current = await self._get_current_model_for_score(model.score_id)
            if old_current is not None and old_current.id != model.id:
                old_current.state = PerformanceCalculationState.SUPERSEDED.value
                old_current.is_current = False
                await self._flush_or_raise_conflict()
            model.is_current = True

        model.claim_owner = None
        model.claim_expires_at = None
        await self._flush_or_raise_conflict()
        await self._session.refresh(model)
        return _model_to_domain(model)

    async def _refresh_batch_progress_from_work_items(
        self,
        batch_id: int,
        *,
        updated_at: datetime,
    ) -> None:
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
        if batch.status == PerformanceRecalculationBatchStatus.COMPLETED.value:
            return
        batch.status = PerformanceRecalculationBatchStatus.RUNNING.value
        batch.updated_at = updated_at

    async def _latest_recalculation_batch_error(self, batch_id: int) -> str | None:
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
        try:
            await self._session.flush()
        except IntegrityError as exc:
            msg = "score performance command conflict; retry the command"
            raise ScorePerformanceCommandConflictError(msg) from exc


def _matches_request(
    model: ScorePerformanceCalculationModel,
    command: CreateScorePerformanceCalculation,
) -> bool:
    return (
        model.calculator_name == command.calculator_name
        and model.calculator_version == command.calculator_version
        and model.formula_profile == command.formula_profile.value
    )


def _model_to_domain(model: ScorePerformanceCalculationModel) -> PerformanceCalculation:
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
    reason_counts = {
        reason: count for reason, count in model.reason_counts.items() if isinstance(count, int)
    }
    return PerformanceRecalculationBatch(
        id=model.id,
        status=PerformanceRecalculationBatchStatus(model.status),
        filters=model.filters,
        reason_counts=reason_counts,
        target_calculator_version=model.target_calculator_version,
        target_formula_profile=FormulaProfile(model.target_formula_profile),
        candidate_count=model.candidate_count,
        completed_count=model.completed_count,
        unavailable_count=model.unavailable_count,
        last_error=last_error,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _work_item_model_to_domain(
    model: PerformanceRecalculationWorkItemModel,
) -> PerformanceRecalculationWorkItem:
    return PerformanceRecalculationWorkItem(
        id=model.id,
        batch_id=model.batch_id,
        score_id=model.score_id,
        reason=model.reason,
        state=PerformanceRecalculationWorkItemState(model.state),
        calculation_id=model.calculation_id,
        claim_owner=model.claim_owner,
        claim_expires_at=model.claim_expires_at,
        attempt_count=model.attempt_count,
        last_error=model.last_error,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
