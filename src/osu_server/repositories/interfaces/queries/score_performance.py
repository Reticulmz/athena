"""Current performance と recalculation candidate 用 read-only repository contract を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from osu_server.domain.scores.performance import (
        FormulaProfile,
        PerformanceCalculation,
        RecalculationCandidateReason,
    )
    from osu_server.domain.scores.score import Ruleset


@dataclass(frozen=True, slots=True)
class ScorePerformanceCandidateSelection:
    """PP recalculation candidate dry-run の read-side filter を表す.

    Attributes:
        target_calculator_name (str): 対象 performance calculator の name.
        target_calculator_version (str): 対象 performance calculator の version.
        target_formula_profile (FormulaProfile): 対象 calculation の formula profile.
        score_id (int | None): 一つの Score に絞る filter. 未指定時は `None`.
        beatmap_id (int | None): 一つの Beatmap に絞る filter. 未指定時は `None`.
        user_id (int | None): 一人の User に絞る filter. 未指定時は `None`.
        ruleset (Ruleset | None): Ruleset に絞る filter. 未指定時は `None`.
        limit (int | None): Candidate の最大数. 未指定時は `None`.
        include_unavailable (bool): Unavailable calculation を candidate に含めるかを表す flag.
        target_beatmap_file_attachment_id (int | None): Target file attachment ID filter.
        target_beatmap_file_checksum_md5 (str | None): Target file MD5 checksum filter.
    """

    target_calculator_name: str
    target_calculator_version: str
    target_formula_profile: FormulaProfile
    score_id: int | None
    beatmap_id: int | None
    user_id: int | None
    ruleset: Ruleset | None
    limit: int | None
    include_unavailable: bool
    target_beatmap_file_attachment_id: int | None = None
    target_beatmap_file_checksum_md5: str | None = None


@dataclass(frozen=True, slots=True)
class ScorePerformanceRecalculationCandidate:
    """Recalculation 対象として選ばれた一つの Score を表す.

    Attributes:
        score_id (int): Recalculation 対象 Score ID.
        reason (RecalculationCandidateReason): Candidate に選ばれた理由.
        current_calculation_id (int | None): 現在の calculation ID. 未作成時は `None`.
    """

    score_id: int
    reason: RecalculationCandidateReason
    current_calculation_id: int | None


@dataclass(frozen=True, slots=True)
class ScorePerformanceRecalculationCandidateResult:
    """Recalculation candidate dry-run の選択結果を表す.

    Attributes:
        candidates (tuple[ScorePerformanceRecalculationCandidate, ...]): 選択された candidate.
        reason_counts (Mapping[RecalculationCandidateReason, int]): Reason ごとの candidate 数.
    """

    candidates: tuple[ScorePerformanceRecalculationCandidate, ...]
    reason_counts: Mapping[RecalculationCandidateReason, int]

    @property
    def candidate_count(self) -> int:
        """選択された recalculation candidate の件数を返す.

        Returns:
            int: `candidates` に含まれる candidate 数.
        """
        return len(self.candidates)


class ScorePerformanceQueryRepository(Protocol):
    """Current PP と recalculation candidate selection 用 read-only port を定義する.

    Notes:
        この Protocol は current calculation と dry-run candidate projection を返すだけである.
        Calculation state や work item を変更せず Command Unit of Work を開始または
        commit/rollback しない.
    """

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        """Score の current PerformanceCalculation だけを返す.

        Args:
            score_id (int): Current calculation を取得する Score ID.

        Returns:
            PerformanceCalculation | None: Current calculation. 未作成の場合は `None`.
        """
        ...

    async def select_recalculation_candidates(
        self,
        selection: ScorePerformanceCandidateSelection,
    ) -> ScorePerformanceRecalculationCandidateResult:
        """Recalculation candidate と dry-run reason count を返す.

        Args:
            selection (ScorePerformanceCandidateSelection): Target calculation と filter を表す
                選択条件.

        Returns:
            ScorePerformanceRecalculationCandidateResult: Candidate と reason ごとの件数.

        Notes:
            この dry-run read は recalculation batch や work item を作成しない.
        """
        ...


__all__ = [
    "ScorePerformanceCandidateSelection",
    "ScorePerformanceQueryRepository",
    "ScorePerformanceRecalculationCandidate",
    "ScorePerformanceRecalculationCandidateResult",
]
