"""Score domain model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.mods import ModCombination


class Ruleset(Enum):
    """Ruleset enum (osu/taiko/catch/mania)."""

    OSU = 0
    TAIKO = 1
    CATCH = 2
    MANIA = 3


class Playstyle(Enum):
    """Playstyle enum (Wave 1: vanilla only)."""

    VANILLA = 0


class Grade(Enum):
    """Grade enum (XH/X/SH/S/A/B/C/D)."""

    XH = "XH"
    X = "X"
    SH = "SH"
    S = "S"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class PlayTimeSource(Enum):
    """play time の submit-time 推定元。"""

    FAIL_TIME = "fail_time"
    BEATMAP_TOTAL_LENGTH = "beatmap_total_length"


@dataclass(slots=True)
class Score:
    """受理済み play attempt と submit-time timing 情報。"""

    id: int | None
    user_id: int
    beatmap_id: int
    beatmap_checksum: str
    online_checksum: str
    ruleset: Ruleset
    playstyle: Playstyle
    mods: ModCombination
    n300: int
    n100: int
    n50: int
    geki: int
    katu: int
    miss: int
    score: int
    max_combo: int
    accuracy: float
    grade: Grade
    passed: bool
    perfect: bool
    client_version: str
    submitted_at: datetime
    beatmap_status_at_submission: str | None = None
    leaderboard_eligible_at_submission: bool = False
    fail_time_ms: int | None = None
    play_time_seconds: int | None = None
    play_time_source: PlayTimeSource | None = None
    submit_exit_classification: str | None = None

    def __post_init__(self) -> None:
        _validate_non_negative_timing("fail_time_ms", self.fail_time_ms)
        _validate_non_negative_timing("play_time_seconds", self.play_time_seconds)


def _validate_non_negative_timing(field_name: str, value: int | None) -> None:
    if value is not None and value < 0:
        msg = f"{field_name} must be non-negative"
        raise ValueError(msg)
