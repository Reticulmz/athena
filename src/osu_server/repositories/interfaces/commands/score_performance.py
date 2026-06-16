"""Command-side score performance repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from osu_server.domain.scores.performance import FormulaProfile, PerformanceCalculation


class ScorePerformanceCommandConflictError(RuntimeError):
    """Raised when concurrent command persistence should be retried."""


@dataclass(frozen=True, slots=True)
class CreateScorePerformanceCalculation:
    """Request a current or replacement performance calculation row."""

    score_id: int
    calculator_name: str
    calculator_version: str
    formula_profile: FormulaProfile
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ScorePerformanceCalculationRequestResult:
    """Result of creating or reusing a calculation request."""

    calculation: PerformanceCalculation
    created: bool
    is_replacement: bool


@dataclass(frozen=True, slots=True)
class ClaimScorePerformanceCalculation:
    """Request ownership of one pending calculation row."""

    calculation_id: int
    owner: str
    claimed_at: datetime
    claim_expires_at: datetime


@dataclass(frozen=True, slots=True)
class ScorePerformanceCalculationClaimResult:
    """Successful pending calculation claim metadata."""

    calculation: PerformanceCalculation
    owner: str
    expires_at: datetime
    attempt_count: int


@dataclass(frozen=True, slots=True)
class CompleteScorePerformanceCalculation:
    """Finalize a calculation with PP and star rating."""

    calculation_id: int
    pp: Decimal
    star_rating: Decimal
    calculator_name: str
    calculator_version: str
    formula_profile: FormulaProfile
    beatmap_file_attachment_id: int
    beatmap_file_checksum_md5: str
    calculated_at: datetime


@dataclass(frozen=True, slots=True)
class MarkScorePerformanceCalculationUnavailable:
    """Finalize a calculation as unavailable with an operator-visible reason."""

    calculation_id: int
    calculator_name: str
    calculator_version: str
    formula_profile: FormulaProfile
    beatmap_file_attachment_id: int | None
    beatmap_file_checksum_md5: str | None
    reason: str
    calculated_at: datetime


class ScorePerformanceCommandRepository(Protocol):
    """Mutation port for performance calculation rows."""

    async def create_or_reuse_calculation(
        self,
        command: CreateScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationRequestResult:
        """Create or reuse a current/replacement calculation request."""
        ...

    async def claim_pending_calculation(
        self,
        command: ClaimScorePerformanceCalculation,
    ) -> ScorePerformanceCalculationClaimResult | None:
        """Claim a pending calculation, returning None on temporary conflict."""
        ...

    async def mark_completed(
        self,
        command: CompleteScorePerformanceCalculation,
    ) -> PerformanceCalculation | None:
        """Finalize a pending calculation as completed."""
        ...

    async def mark_unavailable(
        self,
        command: MarkScorePerformanceCalculationUnavailable,
    ) -> PerformanceCalculation | None:
        """Finalize a pending calculation as unavailable."""
        ...

    async def get_by_id(self, calculation_id: int) -> PerformanceCalculation | None:
        """Return one calculation by id."""
        ...

    async def get_current_for_score(self, score_id: int) -> PerformanceCalculation | None:
        """Return the current calculation for a score."""
        ...
