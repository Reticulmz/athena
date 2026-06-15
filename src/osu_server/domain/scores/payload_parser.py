"""Score payload values shared by score submission workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.mods import ModCombination


class ParseError(Exception):
    """Raised when a score payload cannot be parsed into domain values."""


@dataclass(frozen=True, slots=True)
class ParsedScore:
    """Parsed score data after client-family payload mapping."""

    user_id: int
    username: str
    beatmap_checksum: str
    online_checksum: str
    ruleset: int
    mods: ModCombination
    n300: int
    n100: int
    n50: int
    geki: int
    katu: int
    miss: int
    score: int
    max_combo: int
    perfect: bool
    passed: bool
    client_grade: str | None = None
    client_submitted_at: str | None = None
    client_version: str | None = None
    client_checksum: str | None = None


__all__ = ["ParseError", "ParsedScore"]
