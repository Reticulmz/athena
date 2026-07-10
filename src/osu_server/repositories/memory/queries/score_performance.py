"""In-memory query-side score performance repository."""

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
    """Read-only score performance repository over committed memory state."""

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory: InMemoryUnitOfWorkFactory = uow_factory
        self._eligibility: PerformanceEligibilityPolicy = PerformanceEligibilityPolicy()

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        state = self._factory.snapshot()
        current_id = state.current_performance_calculation_id_by_score_id.get(score_id)
        if current_id is None:
            return None
        return state.performance_calculations_by_id.get(current_id)

    async def select_recalculation_candidates(
        self,
        selection: ScorePerformanceCandidateSelection,
    ) -> ScorePerformanceRecalculationCandidateResult:
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
    keys = state.attachment_keys_by_beatmap_id.get(score.beatmap_id)
    if not keys:
        return None
    return state.attachments_by_key.get(keys[-1])
