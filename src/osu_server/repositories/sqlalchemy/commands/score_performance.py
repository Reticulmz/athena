"""SQLAlchemy command-side score performance repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculation,
    PerformanceCalculationState,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    ScorePerformanceCalculationClaimResult,
    ScorePerformanceCalculationRequestResult,
    ScorePerformanceCommandConflictError,
)
from osu_server.repositories.sqlalchemy.models.score_performance import (
    ScorePerformanceCalculationModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from osu_server.repositories.interfaces.commands.score_performance import (
        ClaimScorePerformanceCalculation,
        CompleteScorePerformanceCalculation,
        CreateScorePerformanceCalculation,
        MarkScorePerformanceCalculationUnavailable,
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
            )

        if _matches_request(current, command):
            return ScorePerformanceCalculationRequestResult(
                calculation=_model_to_domain(current),
                created=False,
                is_replacement=False,
            )

        replacement = await self._get_matching_replacement_model(command)
        if replacement is not None:
            return ScorePerformanceCalculationRequestResult(
                calculation=_model_to_domain(replacement),
                created=False,
                is_replacement=True,
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

    async def _get_matching_replacement_model(
        self,
        command: CreateScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationModel | None:
        model = (
            await self._session.execute(
                select(ScorePerformanceCalculationModel)
                .where(
                    ScorePerformanceCalculationModel.score_id == command.score_id,
                    ScorePerformanceCalculationModel.is_current.is_(False),
                    ScorePerformanceCalculationModel.state.in_(_PENDING_STATE_VALUES),
                    ScorePerformanceCalculationModel.calculator_name == command.calculator_name,
                    ScorePerformanceCalculationModel.calculator_version
                    == command.calculator_version,
                    ScorePerformanceCalculationModel.formula_profile
                    == command.formula_profile.value,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return model if isinstance(model, ScorePerformanceCalculationModel) else None

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
