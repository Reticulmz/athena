"""SQLAlchemy query-side score performance repository."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, cast

from sqlalchemy import and_, func, select

from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculation,
    PerformanceCalculationState,
    PerformanceEligibilityPolicy,
)
from osu_server.domain.scores.score import Playstyle
from osu_server.repositories.interfaces.queries.score_performance import (
    RecalculationCandidateReason,
    ScorePerformanceRecalculationCandidate,
    ScorePerformanceRecalculationCandidateResult,
)
from osu_server.repositories.sqlalchemy.models.beatmap import BeatmapFileAttachmentModel
from osu_server.repositories.sqlalchemy.models.score import ScoreModel
from osu_server.repositories.sqlalchemy.models.score_performance import (
    ScorePerformanceCalculationModel,
)
from osu_server.repositories.sqlalchemy.queries._shared import score_to_domain

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.score_performance import (
        ScorePerformanceCandidateSelection,
    )
    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory

_ROW_TUPLE_LENGTH = 3


class SQLAlchemyScorePerformanceQueryRepository:
    """Read-only score performance repository backed by short SQLAlchemy sessions."""

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        self._session_factory: SQLAlchemyQuerySessionFactory = session_factory
        self._eligibility: PerformanceEligibilityPolicy = PerformanceEligibilityPolicy()

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(ScorePerformanceCalculationModel)
                    .where(
                        ScorePerformanceCalculationModel.score_id == score_id,
                        ScorePerformanceCalculationModel.is_current.is_(True),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            return (
                _model_to_domain(model)
                if isinstance(model, ScorePerformanceCalculationModel)
                else None
            )

    async def select_recalculation_candidates(
        self,
        selection: ScorePerformanceCandidateSelection,
    ) -> ScorePerformanceRecalculationCandidateResult:
        async with self._session_factory() as session:
            rows = (await session.execute(_candidate_statement(selection))).all()

        candidates: list[ScorePerformanceRecalculationCandidate] = []
        for score_model, performance_model, attachment_model in _iter_candidate_rows(rows):
            score = score_to_domain(score_model)
            if not self._eligibility.evaluate(score).is_eligible:
                continue
            current = (
                _model_to_domain(performance_model)
                if isinstance(performance_model, ScorePerformanceCalculationModel)
                else None
            )
            reason = _candidate_reason(current, selection, attachment_model)
            if reason is None:
                continue
            assert score.id is not None
            candidates.append(
                ScorePerformanceRecalculationCandidate(
                    score_id=score.id,
                    reason=reason,
                    current_calculation_id=current.id if current is not None else None,
                )
            )
            if selection.limit is not None and len(candidates) >= selection.limit:
                break

        return ScorePerformanceRecalculationCandidateResult(
            candidates=tuple(candidates),
            reason_counts=dict(Counter(candidate.reason for candidate in candidates)),
        )


def _candidate_statement(selection: ScorePerformanceCandidateSelection):
    latest_attachment = (
        select(
            BeatmapFileAttachmentModel.beatmap_id.label("beatmap_id"),
            func.max(BeatmapFileAttachmentModel.id).label("attachment_id"),
        )
        .group_by(BeatmapFileAttachmentModel.beatmap_id)
        .subquery()
    )
    statement = (
        select(ScoreModel, ScorePerformanceCalculationModel, BeatmapFileAttachmentModel)
        .outerjoin(
            ScorePerformanceCalculationModel,
            and_(
                ScorePerformanceCalculationModel.score_id == ScoreModel.id,
                ScorePerformanceCalculationModel.is_current.is_(True),
            ),
        )
        .outerjoin(latest_attachment, latest_attachment.c.beatmap_id == ScoreModel.beatmap_id)
        .outerjoin(
            BeatmapFileAttachmentModel,
            BeatmapFileAttachmentModel.id == latest_attachment.c.attachment_id,
        )
        .where(
            ScoreModel.passed.is_(True),
            ScoreModel.playstyle == Playstyle.VANILLA.value,
        )
        .order_by(ScoreModel.id.asc())
    )
    if selection.score_id is not None:
        statement = statement.where(ScoreModel.id == selection.score_id)
    if selection.beatmap_id is not None:
        statement = statement.where(ScoreModel.beatmap_id == selection.beatmap_id)
    if selection.user_id is not None:
        statement = statement.where(ScoreModel.user_id == selection.user_id)
    if selection.ruleset is not None:
        statement = statement.where(ScoreModel.ruleset == selection.ruleset.value)
    return statement


def _iter_candidate_rows(
    rows: object,
) -> list[
    tuple[
        ScoreModel,
        ScorePerformanceCalculationModel | None,
        BeatmapFileAttachmentModel | None,
    ]
]:
    result: list[
        tuple[
            ScoreModel,
            ScorePerformanceCalculationModel | None,
            BeatmapFileAttachmentModel | None,
        ]
    ] = []
    for row in cast("list[object]", rows):
        if isinstance(row, tuple):
            values = cast("tuple[object, ...]", row)
            if len(values) == _ROW_TUPLE_LENGTH and isinstance(values[0], ScoreModel):
                performance = (
                    values[1] if isinstance(values[1], ScorePerformanceCalculationModel) else None
                )
                attachment = (
                    values[2] if isinstance(values[2], BeatmapFileAttachmentModel) else None
                )
                result.append((values[0], performance, attachment))
            continue
        score_model = getattr(row, "ScoreModel", None)
        performance_model = getattr(row, "ScorePerformanceCalculationModel", None)
        attachment_model = getattr(row, "BeatmapFileAttachmentModel", None)
        if isinstance(score_model, ScoreModel):
            performance = (
                performance_model
                if isinstance(performance_model, ScorePerformanceCalculationModel)
                else None
            )
            attachment = (
                attachment_model
                if isinstance(attachment_model, BeatmapFileAttachmentModel)
                else None
            )
            result.append((score_model, performance, attachment))
    return result


def _candidate_reason(
    current: PerformanceCalculation | None,
    selection: ScorePerformanceCandidateSelection,
    target_attachment: BeatmapFileAttachmentModel | None,
) -> RecalculationCandidateReason | None:
    reason: RecalculationCandidateReason | None = None
    if current is None:
        reason = RecalculationCandidateReason.UNCALCULATED
    elif current.state.is_pending or current.state.is_historical:
        reason = None
    elif current.state is PerformanceCalculationState.UNAVAILABLE:
        reason = (
            RecalculationCandidateReason.UNAVAILABLE if selection.include_unavailable else None
        )
    elif _is_stale(current, selection, target_attachment):
        reason = RecalculationCandidateReason.STALE
    elif (
        current.calculator_name != selection.target_calculator_name
        or current.calculator_version != selection.target_calculator_version
    ):
        reason = RecalculationCandidateReason.CALCULATOR_VERSION_MISMATCH
    elif current.formula_profile is not selection.target_formula_profile:
        reason = RecalculationCandidateReason.FORMULA_PROFILE_MISMATCH
    return reason


def _is_stale(
    current: PerformanceCalculation,
    selection: ScorePerformanceCandidateSelection,
    target_attachment: BeatmapFileAttachmentModel | None,
) -> bool:
    if target_attachment is not None and (
        current.beatmap_file_attachment_id != target_attachment.id
        or current.beatmap_file_checksum_md5 != target_attachment.checksum_md5
    ):
        return True
    if (
        selection.target_beatmap_file_attachment_id is not None
        and current.beatmap_file_attachment_id != selection.target_beatmap_file_attachment_id
    ):
        return True
    return (
        selection.target_beatmap_file_checksum_md5 is not None
        and current.beatmap_file_checksum_md5 != selection.target_beatmap_file_checksum_md5
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
