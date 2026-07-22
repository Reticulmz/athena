"""Committed in-memory state から Score Performance を読む query adapter を提供する."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from osu_server.domain.scores.performance import (
    PerformanceCalculationState,
    PerformanceEligibilityPolicy,
    RecalculationCandidateReason,
)
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceRecalculationCandidate,
    ScorePerformanceRecalculationCandidateResult,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.beatmaps import BeatmapFileAttachment
    from osu_server.domain.scores.performance import PerformanceCalculation
    from osu_server.domain.scores.score import Score
    from osu_server.repositories.interfaces.queries.score_performance import (
        ScorePerformanceCandidateSelection,
    )
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryScorePerformanceQueryRepository:
    """Committed in-memory state を読む read-only Score Performance repository.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): query ごとの committed snapshot を生成する factory.
        _eligibility (PerformanceEligibilityPolicy): recalculation candidate の eligibility policy.

    Notes:
        各 query は snapshot と policy を読むだけで, Score/Performance state を変更しない.
    """

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Committed snapshot factory と default eligibility policy を初期化する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): read に使用する committed state factory.

        Returns:
            None: factory と PerformanceEligibilityPolicy を保持する repository を構築する.
        """
        self._factory: InMemoryUnitOfWorkFactory = uow_factory
        self._eligibility: PerformanceEligibilityPolicy = PerformanceEligibilityPolicy()

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        """Score に現在として索引付けられた PerformanceCalculation を取得する.

        Args:
            score_id (int): current calculation を取得する Score の ID.

        Returns:
            PerformanceCalculation | None: current calculation ID の索引先.
            索引または calculation がなければ None.

        Notes:
            Calculation の is_current や score_id の整合性は追加で検証しない.
        """
        state = self._factory.snapshot()
        current_id = state.current_performance_calculation_id_by_score_id.get(score_id)
        if current_id is None:
            return None
        return state.performance_calculations_by_id.get(current_id)

    async def select_recalculation_candidates(
        self,
        selection: ScorePerformanceCandidateSelection,
    ) -> ScorePerformanceRecalculationCandidateResult:
        """Selection に一致する Performance recalculation candidate を選出する.

        Args:
            selection (ScorePerformanceCandidateSelection): Score scope, target calculator,
                formula, attachment, unavailable と件数の選択条件.

        Returns:
            ScorePerformanceRecalculationCandidateResult: ID 順で選出した candidate tuple と reason
            ごとの件数.

        Notes:
            ID を持ち policy 上 eligible な Score だけを対象にする. limit は candidate を追加した
            後に判定するため, 条件に一致する candidate があれば 0 以下の limit でも一件返す.
            state を変更しない.
        """
        state = self._factory.snapshot()
        candidates: list[ScorePerformanceRecalculationCandidate] = []

        for score in _filter_scores(state.scores_by_id.values(), selection):
            if score.id is None:
                continue
            if not self._eligibility.evaluate(score).is_eligible:
                continue
            current_id = state.current_performance_calculation_id_by_score_id.get(score.id)
            current = (
                state.performance_calculations_by_id.get(current_id)
                if current_id is not None
                else None
            )
            target_attachment = _current_attachment_for_score(score, state)
            reason = _candidate_reason(current, selection, target_attachment)
            if reason is None:
                continue
            candidates.append(
                ScorePerformanceRecalculationCandidate(
                    score_id=score.id,
                    reason=reason,
                    current_calculation_id=current.id if current is not None else None,
                )
            )
            if selection.limit is not None and len(candidates) >= selection.limit:
                break

        reason_counts = Counter(candidate.reason for candidate in candidates)
        return ScorePerformanceRecalculationCandidateResult(
            candidates=tuple(candidates),
            reason_counts=dict(reason_counts),
        )


def _filter_scores(
    scores: Iterable[Score],
    selection: ScorePerformanceCandidateSelection,
) -> list[Score]:
    """Selection の指定済み scope に一致する Score を ID 順で絞り込む.

    Args:
        scores (Iterable[Score]): 絞り込む Score 群.
        selection (ScorePerformanceCandidateSelection): score/beatmap/user/ruleset の filter 条件.

    Returns:
        list[Score]: 指定済みの全 filter に一致する Score を score.id または 0 の昇順にした list.

    Notes:
        None の filter field は絞り込みを行わない. 入力 iterable の Score を変更しない.
    """
    filtered = sorted(scores, key=lambda score: score.id or 0)
    if selection.score_id is not None:
        filtered = [score for score in filtered if score.id == selection.score_id]
    if selection.beatmap_id is not None:
        filtered = [score for score in filtered if score.beatmap_id == selection.beatmap_id]
    if selection.user_id is not None:
        filtered = [score for score in filtered if score.user_id == selection.user_id]
    if selection.ruleset is not None:
        filtered = [score for score in filtered if score.ruleset is selection.ruleset]
    return filtered


def _candidate_reason(
    current: PerformanceCalculation | None,
    selection: ScorePerformanceCandidateSelection,
    target_attachment: BeatmapFileAttachment | None,
) -> RecalculationCandidateReason | None:
    """Current calculation と target 条件の差分から candidate reason を選ぶ.

    Args:
        current (PerformanceCalculation | None): Score の current calculation. なければ None.
        selection (ScorePerformanceCandidateSelection): target calculator, formula,
            attachment 条件.
        target_attachment (BeatmapFileAttachment | None): Score Beatmap の現在 attachment.

    Returns:
        RecalculationCandidateReason | None: UNCALCULATED, UNAVAILABLE, STALE, calculator version
        mismatch, formula profile mismatch のいずれか. 再計算不要または対象外なら None.

    Notes:
        pending/historical calculation は None を返す. 判定順は未計算, pending/historical,
        unavailable, stale, calculator version, formula profile である.
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
    target_attachment: BeatmapFileAttachment | None,
) -> bool:
    """Current calculation が target attachment 条件に対して stale かを判定する.

    Args:
        current (PerformanceCalculation): 判定する current calculation.
        selection (ScorePerformanceCandidateSelection): target attachment ID と checksum 条件.
        target_attachment (BeatmapFileAttachment | None): Score Beatmap の現在 attachment.

    Returns:
        bool: 現在 attachment checksum, target attachment ID, target checksum のいずれかが
            不一致なら True. 指定された条件がすべて一致または未指定なら False.

    Notes:
        判定対象を変更しない.
    """
    if (
        target_attachment is not None
        and current.beatmap_file_checksum_md5 != target_attachment.checksum_md5
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


def _current_attachment_for_score(
    score: Score,
    state: InMemoryCommandRepositoryState,
) -> BeatmapFileAttachment | None:
    """Score Beatmap の最後に記録された file attachment を取得する.

    Args:
        score (Score): attachment を検索する Score.
        state (InMemoryCommandRepositoryState): attachment key と attachment 索引を含む snapshot.

    Returns:
        BeatmapFileAttachment | None: attachment key の末尾に対応する attachment. key がなければ
        None. key があっても attachment 索引に値がなければ None.

    Notes:
        state と score を変更しない.
    """
    keys = state.attachment_keys_by_beatmap_id.get(score.beatmap_id)
    if not keys:
        return None
    return state.attachments_by_key.get(keys[-1])
