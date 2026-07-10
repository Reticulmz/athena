"""Beatmap leaderboard domain policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Self

from osu_server.domain.scores.mods import Mod, ModCombination

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.score import Playstyle, Ruleset


ALL_MODS_FILTER_KEY: Final[int] = -1
NO_MOD_FILTER_KEY: Final[int] = 0

_MIRROR_SELECTED_FILTER_KEY: Final[None] = None
_PREFERENCE_ONLY_NO_MODS: Final[Mod] = Mod.SUDDEN_DEATH | Mod.PERFECT | Mod.MIRROR


@dataclass(slots=True, frozen=True)
class ScoreRankKey:
    """Score-priority ordering key for Beatmap Leaderboard candidates."""

    score: int
    submitted_at: datetime
    score_id: int

    def __post_init__(self) -> None:
        if self.score < 0:
            msg = "score must not be negative"
            raise ValueError(msg)
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)

    @property
    def ordering_key(self) -> tuple[int, datetime, int]:
        """Return a sortable key for score desc, submitted_at asc, score_id asc."""
        return (-self.score, self.submitted_at, self.score_id)


@dataclass(slots=True, frozen=True)
class LeaderboardScope:
    """Identity dimensions for one Beatmap Leaderboard candidate scope."""

    beatmap_id: int
    ruleset: Ruleset
    playstyle: Playstyle
    mod_filter_key: int = ALL_MODS_FILTER_KEY

    def __post_init__(self) -> None:
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)
        if self.mod_filter_key < ALL_MODS_FILTER_KEY:
            msg = "mod_filter_key must be all-mods sentinel or non-negative"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class LeaderboardModFilter:
    """Canonical selected-mods filter key for Beatmap Leaderboards."""

    key: int | None
    unsupported: bool = False

    def __post_init__(self) -> None:
        if self.unsupported and self.key is not None:
            msg = "unsupported mod filter must not expose a key"
            raise ValueError(msg)
        if not self.unsupported and self.key is not None and self.key < ALL_MODS_FILTER_KEY:
            msg = "mod filter key must be all-mods sentinel or non-negative"
            raise ValueError(msg)

    @classmethod
    def all_mods(cls) -> Self:
        return cls(key=ALL_MODS_FILTER_KEY)

    @classmethod
    def unsupported_filter(cls) -> Self:
        return cls(key=_MIRROR_SELECTED_FILTER_KEY, unsupported=True)

    @property
    def is_supported(self) -> bool:
        return not self.unsupported

    @property
    def is_all_mods(self) -> bool:
        return self.is_supported and self.key == ALL_MODS_FILTER_KEY

    @property
    def is_no_mod(self) -> bool:
        return self.is_supported and self.key == NO_MOD_FILTER_KEY


def score_beats_current(candidate: ScoreRankKey, current: ScoreRankKey | None) -> bool:
    """Return whether candidate ranks above the current representative score."""
    if current is None:
        return True
    return candidate.ordering_key < current.ordering_key


def filter_from_mod_combination(mods: ModCombination) -> LeaderboardModFilter:
    """Normalize a selected-mod filter into a canonical leaderboard key."""
    if mods.has(Mod.MIRROR):
        return LeaderboardModFilter.unsupported_filter()

    return LeaderboardModFilter(key=_canonical_filter_key(mods))


def projection_keys_for_score(mods: ModCombination) -> tuple[int, ...]:
    """Return all leaderboard mod filter keys a source score can project into."""
    keys: list[int] = [ALL_MODS_FILTER_KEY]
    if _is_no_mod_candidate(mods):
        keys.append(NO_MOD_FILTER_KEY)

    canonical_key = _canonical_filter_key(mods)
    if canonical_key != NO_MOD_FILTER_KEY and canonical_key not in keys:
        keys.append(canonical_key)

    return tuple(keys)


def _is_no_mod_candidate(mods: ModCombination) -> bool:
    gameplay_bits = _canonical_filter_key(mods) & ~int(_PREFERENCE_ONLY_NO_MODS)
    return gameplay_bits == 0


def _canonical_filter_key(mods: ModCombination) -> int:
    bits = mods.to_persistence_bitmask()
    if mods.has(Mod.NIGHTCORE):
        bits |= int(Mod.DOUBLE_TIME)
        bits &= ~int(Mod.NIGHTCORE)
    if mods.has(Mod.PERFECT):
        bits |= int(Mod.SUDDEN_DEATH)
        bits &= ~int(Mod.PERFECT)

    bits &= ~int(Mod.MIRROR)
    return bits


__all__ = [
    "ALL_MODS_FILTER_KEY",
    "NO_MOD_FILTER_KEY",
    "LeaderboardModFilter",
    "LeaderboardScope",
    "ScoreRankKey",
    "filter_from_mod_combination",
    "projection_keys_for_score",
    "score_beats_current",
]
