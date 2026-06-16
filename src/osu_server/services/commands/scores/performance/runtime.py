"""Runtime settings for score performance command workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING

from osu_server.domain.scores.performance import FormulaProfile
from osu_server.domain.scores.score import Playstyle

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_PERFORMANCE_BOUNDED_WAIT = timedelta(seconds=5)
DEFAULT_PERFORMANCE_WORKER_CHUNK_SIZE = 100
DEFAULT_PERFORMANCE_CLAIM_TIMEOUT = timedelta(minutes=5)


def _default_formula_profiles_by_playstyle() -> dict[Playstyle, FormulaProfile]:
    return {Playstyle.VANILLA: FormulaProfile.VANILLA_RANKED}


@dataclass(slots=True, frozen=True)
class PerformanceRuntimeSettings:
    """Typed runtime defaults for the score performance subsystem."""

    bounded_wait: timedelta = DEFAULT_PERFORMANCE_BOUNDED_WAIT
    formula_profiles_by_playstyle: Mapping[Playstyle, FormulaProfile] = field(
        default_factory=_default_formula_profiles_by_playstyle
    )
    worker_chunk_size: int = DEFAULT_PERFORMANCE_WORKER_CHUNK_SIZE
    claim_timeout: timedelta = DEFAULT_PERFORMANCE_CLAIM_TIMEOUT

    def __post_init__(self) -> None:
        if self.bounded_wait <= timedelta(0):
            msg = "bounded_wait must be positive"
            raise ValueError(msg)
        if self.worker_chunk_size <= 0:
            msg = "worker_chunk_size must be positive"
            raise ValueError(msg)
        if self.claim_timeout <= timedelta(0):
            msg = "claim_timeout must be positive"
            raise ValueError(msg)
        profiles = dict(self.formula_profiles_by_playstyle)
        if Playstyle.VANILLA not in profiles:
            msg = "vanilla formula profile is required"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "formula_profiles_by_playstyle",
            MappingProxyType(profiles),
        )

    def active_formula_profile_for(self, playstyle: Playstyle) -> FormulaProfile:
        profile = self.formula_profiles_by_playstyle.get(playstyle)
        if profile is None:
            msg = f"unsupported playstyle for performance calculation: {playstyle!r}"
            raise ValueError(msg)
        return profile
