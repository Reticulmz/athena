"""stable getscores の互換表現。

legacy ``/web/osu-osz2-getscores.php`` の parse 結果、解決結果、
表示用 personal best を transport から独立した値として表す。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps import Beatmap, BeatmapSet
    from osu_server.domain.scores.leaderboards import LeaderboardModFilter
    from osu_server.domain.scores.personal_best import LeaderboardCategory
    from osu_server.domain.scores.score import Playstyle, Ruleset


class GetscoresParseError(Enum):
    """getscores query を request に変換できない致命的な理由。"""

    MISSING_IDENTITY = "missing_identity"
    INVALID_CHECKSUM = "invalid_checksum"


class GetscoresParseWarning(Enum):
    """互換レスポンスは続行できるが入力値を無視した理由。"""

    INVALID_MODE = "invalid_mode"
    INVALID_MODS = "invalid_mods"
    INVALID_LEADERBOARD_TYPE = "invalid_leaderboard_type"
    INVALID_LEADERBOARD_VERSION = "invalid_leaderboard_version"
    INVALID_SONG_SELECT_FLAG = "invalid_song_select_flag"
    INVALID_ANTI_CHEAT_SIGNAL = "invalid_anti_cheat_signal"
    INVALID_BEATMAPSET_ID_HINT = "invalid_beatmapset_id_hint"


@dataclass(slots=True, frozen=True)
class StableLeaderboardSelection:
    """stable client の leaderboard 選択状態。"""

    category: LeaderboardCategory | None
    selected_mod_filter: LeaderboardModFilter | None
    header_only: bool
    unsupported: bool = False


@dataclass(slots=True, frozen=True)
class GetscoresRequest:
    """stable getscores query を正規化した request。"""

    checksum_md5: str | None
    filename: str | None
    beatmapset_id_hint: int | None
    mode: int | None
    mods: int | None
    leaderboard_type: int | None
    leaderboard_version: int | None
    song_select: bool | None
    leaderboard_selection: StableLeaderboardSelection | None = None
    anti_cheat_signal: bool = False
    parse_warnings: tuple[GetscoresParseWarning, ...] = ()


@dataclass(slots=True, frozen=True)
class GetscoresParseResult:
    """getscores parse の成功 request または失敗理由。"""

    request: GetscoresRequest | None = None
    error: GetscoresParseError | None = None


class GetscoresOutcomeKind(Enum):
    """stable getscores が返す高水準の response 種別。"""

    HEADER = "header"
    UNAVAILABLE = "unavailable"
    UPDATE_AVAILABLE = "update_available"


class GetscoresResolveReason(Enum):
    """getscores 解決結果になった理由。"""

    KNOWN_CHECKSUM = "known_checksum"
    KNOWN_FILENAME_IN_SET = "known_filename_in_set"
    NOT_SUBMITTED = "not_submitted"
    NOT_FOUND = "not_found"
    PENDING_FETCH = "pending_fetch"
    FAILED_METADATA = "failed_metadata"
    UPDATE_AVAILABLE = "update_available"


@dataclass(slots=True, frozen=True)
class GetscoresPersonalBest:
    """stable personal-best 欄にそのまま写せる score 表示値。"""

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
    """beatmap header と leaderboard 行をまとめた解決済み表示値。"""

    beatmap: Beatmap
    beatmapset: BeatmapSet
    personal_best: GetscoresPersonalBest | None = None
    score_rows: tuple[GetscoresPersonalBest, ...] = ()


@dataclass(slots=True, frozen=True)
class GetscoresResolveOutcome:
    """getscores query が response builder に渡す解決結果。"""

    kind: GetscoresOutcomeKind
    header: GetscoresResolvedHeader | None
    reason: GetscoresResolveReason
