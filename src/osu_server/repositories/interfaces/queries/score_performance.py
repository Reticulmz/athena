"""Query-side score performance repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.scores.performance import RecalculationCandidateReason

if TYPE_CHECKING:
    from collections.abc import Mapping

    from osu_server.domain.scores.performance import (
        FormulaProfile,
        PerformanceCalculation,
    )
    from osu_server.domain.scores.score import Ruleset


@dataclass(frozen=True, slots=True)
class ScorePerformanceCandidateSelection:
    """Read-side filters for PP recalculation candidate dry-run."""

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
    """One score selected for recalculation."""

    score_id: int
    reason: RecalculationCandidateReason
    current_calculation_id: int | None


@dataclass(frozen=True, slots=True)
class ScorePerformanceRecalculationCandidateResult:
    """Dry-run candidate selection result."""

    candidates: tuple[ScorePerformanceRecalculationCandidate, ...]
    reason_counts: Mapping[RecalculationCandidateReason, int]

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)


class ScorePerformanceQueryRepository(Protocol):
    """Read-only port for current PP and recalculation candidate selection."""

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        """Return only the current Performance Calculation for a score."""
        ...

    async def select_recalculation_candidates(
        self,
        selection: ScorePerformanceCandidateSelection,
    ) -> ScorePerformanceRecalculationCandidateResult:
        """Return recalculation candidates and dry-run reason counts."""
        ...


__all__ = [
    "RecalculationCandidateReason",
    "ScorePerformanceCandidateSelection",
    "ScorePerformanceQueryRepository",
    "ScorePerformanceRecalculationCandidate",
    "ScorePerformanceRecalculationCandidateResult",
]
