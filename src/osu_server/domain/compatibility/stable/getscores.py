from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps import Beatmap, BeatmapSet
    from osu_server.domain.scores.score import Playstyle, Ruleset


class GetscoresParseError(Enum):
    MISSING_IDENTITY = "missing_identity"
    INVALID_CHECKSUM = "invalid_checksum"


class GetscoresParseWarning(Enum):
    INVALID_MODE = "invalid_mode"
    INVALID_MODS = "invalid_mods"
    INVALID_LEADERBOARD_TYPE = "invalid_leaderboard_type"
    INVALID_LEADERBOARD_VERSION = "invalid_leaderboard_version"
    INVALID_SONG_SELECT_FLAG = "invalid_song_select_flag"
    INVALID_ANTI_CHEAT_SIGNAL = "invalid_anti_cheat_signal"
    INVALID_BEATMAPSET_ID_HINT = "invalid_beatmapset_id_hint"


@dataclass(slots=True, frozen=True)
class GetscoresRequest:
    checksum_md5: str | None
    filename: str | None
    beatmapset_id_hint: int | None
    mode: int | None
    mods: int | None
    leaderboard_type: int | None
    leaderboard_version: int | None
    song_select: bool | None
    anti_cheat_signal: bool = False
    parse_warnings: tuple[GetscoresParseWarning, ...] = ()


@dataclass(slots=True, frozen=True)
class GetscoresParseResult:
    request: GetscoresRequest | None = None
    error: GetscoresParseError | None = None


class GetscoresOutcomeKind(Enum):
    HEADER = "header"
    UNAVAILABLE = "unavailable"
    UPDATE_AVAILABLE = "update_available"


class GetscoresResolveReason(Enum):
    KNOWN_CHECKSUM = "known_checksum"
    KNOWN_FILENAME_IN_SET = "known_filename_in_set"
    NOT_SUBMITTED = "not_submitted"
    NOT_FOUND = "not_found"
    PENDING_FETCH = "pending_fetch"
    FAILED_METADATA = "failed_metadata"
    UPDATE_AVAILABLE = "update_available"


@dataclass(slots=True, frozen=True)
class GetscoresPersonalBest:
    """Display-ready score data for the stable personal-best section."""

    score_id: int
    user_id: int
    username: str
    beatmap_id: int
    ruleset: Ruleset
    playstyle: Playstyle
    score: int
    max_combo: int
    n50: int
    n100: int
    n300: int
    miss: int
    katu: int
    geki: int
    perfect: bool
    mods: int
    rank: int
    submitted_at: datetime
    has_replay: bool


@dataclass(slots=True, frozen=True)
class GetscoresResolvedHeader:
    beatmap: Beatmap
    beatmapset: BeatmapSet
    personal_best: GetscoresPersonalBest | None = None
    score_rows: tuple[GetscoresPersonalBest, ...] = ()


@dataclass(slots=True, frozen=True)
class GetscoresResolveOutcome:
    kind: GetscoresOutcomeKind
    header: GetscoresResolvedHeader | None
    reason: GetscoresResolveReason
