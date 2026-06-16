"""Command-side score performance repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from decimal import Decimal

    from osu_server.domain.scores.performance import (
        FormulaProfile,
        PerformanceCalculation,
        PerformanceRecalculationBatch,
        PerformanceRecalculationWorkItem,
    )


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
    requires_commit: bool = False


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


@dataclass(frozen=True, slots=True)
class CreateScorePerformanceRecalculationWorkItem:
    """One score selected for durable recalculation work."""

    score_id: int
    reason: str


@dataclass(frozen=True, slots=True)
class CreateScorePerformanceRecalculationBatch:
    """Create one durable recalculation batch and its work items."""

    filters: Mapping[str, object]
    reason_counts: Mapping[str, int]
    target_calculator_version: str
    target_formula_profile: FormulaProfile
    work_items: tuple[CreateScorePerformanceRecalculationWorkItem, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ClaimScorePerformanceRecalculationWork:
    """Claim a bounded chunk of pending or stale recalculation work."""

    batch_id: int
    owner: str
    claimed_at: datetime
    claim_expires_at: datetime
    limit: int


@dataclass(frozen=True, slots=True)
class CompleteScorePerformanceRecalculationWork:
    """Mark one recalculation work item completed."""

    work_item_id: int
    owner: str
    calculation_id: int
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class MarkScorePerformanceRecalculationWorkUnavailable:
    """Mark one recalculation work item unavailable."""

    work_item_id: int
    owner: str
    calculation_id: int
    reason: str
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class MarkScorePerformanceRecalculationWorkFailed:
    """Record one retryable recalculation work failure."""

    work_item_id: int
    owner: str
    error: str
    failed_at: datetime


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

    async def create_recalculation_batch(
        self,
        command: CreateScorePerformanceRecalculationBatch,
    ) -> PerformanceRecalculationBatch:
        """Create one recalculation batch with all selected work items."""
        ...

    async def claim_recalculation_work(
        self,
        command: ClaimScorePerformanceRecalculationWork,
    ) -> tuple[PerformanceRecalculationWorkItem, ...]:
        """Claim pending or stale recalculation work items in a bounded chunk."""
        ...

    async def mark_recalculation_work_completed(
        self,
        command: CompleteScorePerformanceRecalculationWork,
    ) -> PerformanceRecalculationWorkItem | None:
        """Mark one recalculation work item completed and update batch progress."""
        ...

    async def mark_recalculation_work_unavailable(
        self,
        command: MarkScorePerformanceRecalculationWorkUnavailable,
    ) -> PerformanceRecalculationWorkItem | None:
        """Mark one recalculation work item unavailable and update batch progress."""
        ...

    async def mark_recalculation_work_failed(
        self,
        command: MarkScorePerformanceRecalculationWorkFailed,
    ) -> PerformanceRecalculationWorkItem | None:
        """Record a retryable work item failure and release it for retry."""
        ...

    async def get_recalculation_batch_by_id(
        self,
        batch_id: int,
    ) -> PerformanceRecalculationBatch | None:
        """Return operator-visible recalculation batch progress."""
        ...

    async def get_recalculation_work_item_by_id(
        self,
        work_item_id: int,
    ) -> PerformanceRecalculationWorkItem | None:
        """Return one recalculation work item by id."""
        ...
