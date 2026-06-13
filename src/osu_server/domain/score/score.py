"""Score domain model."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


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


@dataclass(slots=True)
class Score:
    """Score domain model."""

    id: int | None
    user_id: int
    beatmap_id: int
    beatmap_checksum: str
    online_checksum: str
    ruleset: Ruleset
    playstyle: Playstyle
    mods: int
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
