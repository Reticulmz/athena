"""Performance calculation domain model and policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import Mod
from osu_server.domain.scores.score import Playstyle

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from osu_server.domain.scores.score import Score

_MD5_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class PerformanceCalculationState(Enum):
    """Lifecycle state for one performance calculation attempt."""

    QUEUED = "queued"
    FETCHING_FILE = "fetching_file"
    CALCULATING = "calculating"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    SUPERSEDED = "superseded"

    @classmethod
    def pending_states(cls) -> frozenset[PerformanceCalculationState]:
        return frozenset({cls.QUEUED, cls.FETCHING_FILE, cls.CALCULATING})

    @classmethod
    def terminal_states(cls) -> frozenset[PerformanceCalculationState]:
        return frozenset({cls.COMPLETED, cls.UNAVAILABLE})

    @property
    def is_pending(self) -> bool:
        return self in self.pending_states()

    @property
    def is_terminal(self) -> bool:
        return self in self.terminal_states()

    @property
    def is_historical(self) -> bool:
        return self is self.SUPERSEDED


class FormulaProfile(Enum):
    """Playstyle-scoped formula profile key."""

    VANILLA_RANKED = "vanilla_ranked_v1"


_DEFAULT_FORMULA_PROFILES_BY_PLAYSTYLE: Mapping[Playstyle, FormulaProfile] = MappingProxyType(
    {Playstyle.VANILLA: FormulaProfile.VANILLA_RANKED}
)


@dataclass(slots=True, frozen=True)
class PerformanceCalculation:
    """One PP calculation attempt or result for a score."""

    id: int | None
    score_id: int
    state: PerformanceCalculationState
    is_current: bool
    pp: Decimal | None
    star_rating: Decimal | None
    calculator_name: str
    calculator_version: str
    formula_profile: FormulaProfile
    beatmap_file_attachment_id: int | None
    beatmap_file_checksum_md5: str | None
    unavailable_reason: str | None
    calculated_at: datetime | None

    def __post_init__(self) -> None:
        _validate_identity(self)
        _validate_provenance(self)
        _validate_state_payload(self)


@dataclass(slots=True, frozen=True)
class PerformanceEligibilityDecision:
    """Wave 2 ranked PP eligibility decision."""

    is_eligible: bool
    reason: str | None


class PerformanceEligibilityPolicy:
    """Decide whether a score enters Wave 2 ranked PP scope."""

    def evaluate(self, score: Score) -> PerformanceEligibilityDecision:
        if not score.passed:
            return PerformanceEligibilityDecision(False, "score_failed")
        if score.playstyle is not Playstyle.VANILLA:
            return PerformanceEligibilityDecision(False, "playstyle_out_of_scope")
        if score.mods.has(Mod.RELAX) or score.mods.has(Mod.AUTOPILOT):
            return PerformanceEligibilityDecision(False, "playstyle_out_of_scope")
        status = _score_status(score)
        if status is None:
            return PerformanceEligibilityDecision(False, "beatmap_status_missing")
        if status not in _RANKED_PP_STATUSES:
            return PerformanceEligibilityDecision(False, "beatmap_status_out_of_scope")
        return PerformanceEligibilityDecision(True, None)


class FormulaProfilePolicy:
    """Resolve exactly one active Formula Profile per playstyle."""

    def __init__(
        self,
        profiles_by_playstyle: Mapping[Playstyle, FormulaProfile] | None = None,
    ) -> None:
        profiles = dict(
            _DEFAULT_FORMULA_PROFILES_BY_PLAYSTYLE
            if profiles_by_playstyle is None
            else profiles_by_playstyle
        )
        if Playstyle.VANILLA not in profiles:
            msg = "vanilla formula profile is required"
            raise ValueError(msg)
        self._profiles_by_playstyle: Mapping[Playstyle, FormulaProfile] = MappingProxyType(
            profiles
        )

    @property
    def profiles_by_playstyle(self) -> Mapping[Playstyle, FormulaProfile]:
        return self._profiles_by_playstyle

    def active_profile_for(self, playstyle: object) -> FormulaProfile:
        if isinstance(playstyle, Playstyle):
            profile = self._profiles_by_playstyle.get(playstyle)
            if profile is not None:
                return profile
        msg = f"unsupported playstyle for performance calculation: {playstyle!r}"
        raise ValueError(msg)


_RANKED_PP_STATUSES = frozenset({BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED})


def _score_status(score: Score) -> BeatmapRankStatus | None:
    raw_status = score.beatmap_status_at_submission
    if raw_status is None:
        return None
    try:
        return BeatmapRankStatus(raw_status)
    except ValueError:
        return BeatmapRankStatus.UNKNOWN


def _validate_identity(calculation: PerformanceCalculation) -> None:
    if calculation.id is not None and calculation.id <= 0:
        msg = "performance calculation id must be positive"
        raise ValueError(msg)
    if calculation.score_id <= 0:
        msg = "score_id must be positive"
        raise ValueError(msg)


def _validate_provenance(calculation: PerformanceCalculation) -> None:
    if calculation.calculator_name == "":
        msg = "calculator_name is required"
        raise ValueError(msg)
    if calculation.calculator_version == "":
        msg = "calculator_version is required"
        raise ValueError(msg)
    attachment_id = calculation.beatmap_file_attachment_id
    if attachment_id is not None and attachment_id <= 0:
        msg = "beatmap_file_attachment_id must be positive"
        raise ValueError(msg)
    checksum = calculation.beatmap_file_checksum_md5
    if checksum is not None and _MD5_PATTERN.fullmatch(checksum) is None:
        msg = "beatmap_file_checksum_md5 must be a 32-character lowercase hexadecimal string"
        raise ValueError(msg)


def _validate_state_payload(calculation: PerformanceCalculation) -> None:
    if calculation.state.is_pending:
        _validate_pending_payload(calculation)
        return
    if calculation.state is PerformanceCalculationState.COMPLETED:
        _validate_completed_payload(calculation)
        return
    if calculation.state is PerformanceCalculationState.UNAVAILABLE:
        _validate_unavailable_payload(calculation)
        return
    if calculation.state is PerformanceCalculationState.SUPERSEDED and calculation.is_current:
        msg = "superseded calculation cannot be current"
        raise ValueError(msg)


def _validate_pending_payload(calculation: PerformanceCalculation) -> None:
    if calculation.pp is not None or calculation.star_rating is not None:
        msg = "pending calculation cannot have pp or star rating"
        raise ValueError(msg)
    if calculation.unavailable_reason is not None:
        msg = "pending calculation cannot have unavailable reason"
        raise ValueError(msg)
    if calculation.calculated_at is not None:
        msg = "pending calculation cannot have calculated timestamp"
        raise ValueError(msg)


def _validate_completed_payload(calculation: PerformanceCalculation) -> None:
    if calculation.pp is None or calculation.star_rating is None:
        msg = "completed calculation requires pp and star rating"
        raise ValueError(msg)
    if calculation.pp < Decimal("0") or calculation.star_rating < Decimal("0"):
        msg = "completed calculation pp and star rating must be non-negative"
        raise ValueError(msg)
    if calculation.unavailable_reason is not None:
        msg = "completed calculation cannot have unavailable reason"
        raise ValueError(msg)
    if calculation.calculated_at is None:
        msg = "completed calculation requires calculated timestamp"
        raise ValueError(msg)


def _validate_unavailable_payload(calculation: PerformanceCalculation) -> None:
    if calculation.pp is not None or calculation.star_rating is not None:
        msg = "unavailable calculation cannot have pp or star rating"
        raise ValueError(msg)
    if calculation.unavailable_reason is None or calculation.unavailable_reason == "":
        msg = "unavailable calculation requires unavailable reason"
        raise ValueError(msg)
    if calculation.calculated_at is None:
        msg = "unavailable calculation requires calculated timestamp"
        raise ValueError(msg)


__all__ = [
    "FormulaProfile",
    "FormulaProfilePolicy",
    "PerformanceCalculation",
    "PerformanceCalculationState",
    "PerformanceEligibilityDecision",
    "PerformanceEligibilityPolicy",
]
