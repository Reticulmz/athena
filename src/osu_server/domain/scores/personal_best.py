"""Personal best projection domain values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Playstyle, Ruleset

UNKNOWN_COUNTRY_CODE = "XX"


class LeaderboardCategory(Enum):
    """Beatmap leaderboard category dimension."""

    GLOBAL = "global"
    COUNTRY = "country"
    SELECTED_MODS = "selected_mods"
    FRIENDS = "friends"


def country_leaderboard_is_available(country: str | None) -> bool:
    """Return whether country leaderboard reads can produce rows."""
    return country is not None and country != UNKNOWN_COUNTRY_CODE


def friends_leaderboard_is_available(eligible_user_ids: tuple[int, ...] | None) -> bool:
    """Return whether friends leaderboard reads can produce rows."""
    return bool(eligible_user_ids)


@dataclass(slots=True, frozen=True)
class PersonalBestScope:
    """Identity dimensions for one personal best projection."""

    user_id: int
    beatmap_id: int
    ruleset: Ruleset
    playstyle: Playstyle
    category: LeaderboardCategory

    def __post_init__(self) -> None:
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class PersonalBest:
    """Current representative score for one personal best scope."""

    id: int | None
    scope: PersonalBestScope
    score_id: int
    ranking_value: int

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            msg = "personal best id must be positive"
            raise ValueError(msg)
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)
        if self.ranking_value < 0:
            msg = "ranking_value must not be negative"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class PersonalBestDelta:
    """Before/after personal best score ids for a score submission."""

    before_score_id: int | None
    before_score: int | None
    before_max_combo: int | None
    before_accuracy: float | None
    after_score_id: int | None
    after_score: int | None
    after_max_combo: int | None
    after_accuracy: float | None
    updated: bool


def score_beats_personal_best(candidate_value: int, current_value: int | None) -> bool:
    """Return whether a candidate ranking value replaces the current best."""
    if current_value is None:
        return True
    return candidate_value > current_value
