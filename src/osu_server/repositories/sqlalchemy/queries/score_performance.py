"""SQLAlchemyからScore performance calculationをread-onlyで取得するquery repositoryを提供する."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, cast

from sqlalchemy import and_, func, select

from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculation,
    PerformanceCalculationState,
    PerformanceEligibilityPolicy,
    RecalculationCandidateReason,
)
from osu_server.domain.scores.score import Playstyle
from osu_server.repositories.interfaces.queries.score_performance import (
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
    """短命なSQLAlchemy read sessionでScore performance calculationを取得する.

    Attributes:
        _session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread sessionのfactory.
        _eligibility (PerformanceEligibilityPolicy): recalculation候補を判定するpolicy.
    """

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """読み取り用session factoryとeligibility policyを保持してrepositoryを初期化する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): query用の非同期read session factory.

        Notes:
            policyはdefault設定で生成し,初期化時にはsessionを生成しない.
        """
        self._session_factory: SQLAlchemyQuerySessionFactory = session_factory
        self._eligibility: PerformanceEligibilityPolicy = PerformanceEligibilityPolicy()

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        """Scoreに対するcurrent performance calculationを取得する.

        Args:
            score_id (int): calculationを検索するScoreの永続ID.

        Returns:
            PerformanceCalculation | None: is_currentがTrueのdomain calculation.
            対象rowがない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: model.stateまたはmodel.formula_profileをdomain enumへ変換できない場合.

        Notes:
            historical calculationは取得せず,calculation stateは変更しない.
        """
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
        """指定targetと一致しないScore performance calculationの再計算候補を選別する.

        Args:
            selection (ScorePerformanceCandidateSelection): target条件と上限を含む選別条件.

        Returns:
            ScorePerformanceRecalculationCandidateResult: candidateとreason別件数を含む結果.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: candidate Score modelのenum値またはmods bitmask,またはperformance modelの
                state/formula profileをdomain valueへ変換できない場合.

        Notes:
            passedかつVANILLAのeligible Scoreだけを候補にする.
            limitはeligibleな候補を数えた後に適用する.
        """
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
    """再計算判定に必要なScore,current calculation,latest attachmentを読むstatementを構築する.

    Args:
        selection (ScorePerformanceCandidateSelection): Score,Beatmap,User,rulesetの任意filterを
            含む選別条件.

    Returns:
        Select: Score,current calculation,最新Beatmap file attachmentを返すSELECT statement.

    Notes:
        passedかつVANILLAのScoreだけを対象にし,limitはPython側のeligibility判定後に適用する.
    """
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
    """SQLAlchemy result rowを型検証済みrecalculation candidate tupleへ正規化する.

    Args:
        rows (object): tuple形式またはattribute形式のSQLAlchemy result row list.

    Returns:
        list[tuple[ScoreModel, ScorePerformanceCalculationModel | None,
            BeatmapFileAttachmentModel | None]]: Score model,current calculation model,
            latest attachment modelのtuple.
        Score modelを持たないrowは含めない.

    Notes:
        calculationとattachmentはouter join由来のため,型が一致しない場合もNoneとして保持する.
    """
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
    """Current calculationをtarget selectionと比較して再計算reasonを決定する.

    Args:
        current (PerformanceCalculation | None): Scoreに紐づくcurrent calculation. 未計算時はNone.
        selection (ScorePerformanceCandidateSelection): target calculator,formula,Beatmap fileを
            含む選別条件.
        target_attachment (BeatmapFileAttachmentModel | None): ScoreのBeatmapに対する
            最新attachment model.

    Returns:
        RecalculationCandidateReason | None: 再計算が必要なreason.
        pending,historical,完全一致時はNone.

    Notes:
        UNAVAILABLEはselection.include_unavailableがTrueの場合だけ候補にする.
    """
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
    """Current calculationのBeatmap file identityがtargetと異なるかを判定する.

    Args:
        current (PerformanceCalculation): stale判定するcurrent calculation.
        selection (ScorePerformanceCandidateSelection): 明示target attachment IDまたはchecksumを
            含む選別条件.
        target_attachment (BeatmapFileAttachmentModel | None): ScoreのBeatmapに対する
            最新attachment model.

    Returns:
        bool: 最新または明示targetのattachment ID/checksumと一致しない場合はTrue. それ以外はFalse.

    Notes:
        attachmentが未登録の場合は明示targetとの比較だけを行う.
    """
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
    """永続化されたScore performance calculation modelをdomain valueへ変換する.

    Args:
        model (ScorePerformanceCalculationModel): calculation tableから取得済みの永続model.

    Returns:
        PerformanceCalculation: stateとformula profileをdomain enumへ変換したcalculation value.

    Raises:
        ValueError: model.stateまたはmodel.formula_profileを対応するdomain enumへ変換できない場合.

    Notes:
        current flag,claim情報以外のread contract fieldを永続値から転記する.
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
