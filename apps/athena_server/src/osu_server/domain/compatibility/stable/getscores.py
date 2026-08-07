"""Stable getscores の transport-independent compatibility value object を定義する module.

Legacy ``/web/osu-osz2-getscores.php`` の parse 結果, 解決結果,
表示用 personal best を transport から独立した値として表す.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps import Beatmap, BeatmapSet
    from osu_server.domain.scores.mods import ModCombination
    from osu_server.domain.scores.personal_best import LeaderboardCategory
    from osu_server.domain.scores.score import Playstyle, Ruleset


class GetscoresParseError(Enum):
    """Getscores query を request に変換できない致命的な理由を表す enum.

    Attributes:
        MISSING_IDENTITY (GetscoresParseError): checksum と filename のいずれも使えない状態.
        INVALID_CHECKSUM (GetscoresParseError): checksum が互換 request として無効な状態.
    """

    MISSING_IDENTITY = "missing_identity"
    INVALID_CHECKSUM = "invalid_checksum"


class GetscoresParseWarning(Enum):
    """Compatibility response を続行しつつ入力値を無視した理由を表す enum.

    Attributes:
        INVALID_MODE (GetscoresParseWarning): mode 値を無視した理由.
        INVALID_MODS (GetscoresParseWarning): mod bitmask を無視した理由.
        INVALID_LEADERBOARD_TYPE (GetscoresParseWarning): leaderboard type を無視した理由.
        INVALID_LEADERBOARD_VERSION (GetscoresParseWarning): leaderboard version を無視した理由.
        INVALID_SONG_SELECT_FLAG (GetscoresParseWarning): song-select flag を無視した理由.
        INVALID_ANTI_CHEAT_SIGNAL (GetscoresParseWarning): anti-cheat signal を無視した理由.
        INVALID_BEATMAPSET_ID_HINT (GetscoresParseWarning): beatmapset ID hint を無視した理由.
    """

    INVALID_MODE = "invalid_mode"
    INVALID_MODS = "invalid_mods"
    INVALID_LEADERBOARD_TYPE = "invalid_leaderboard_type"
    INVALID_LEADERBOARD_VERSION = "invalid_leaderboard_version"
    INVALID_SONG_SELECT_FLAG = "invalid_song_select_flag"
    INVALID_ANTI_CHEAT_SIGNAL = "invalid_anti_cheat_signal"
    INVALID_BEATMAPSET_ID_HINT = "invalid_beatmapset_id_hint"


@dataclass(slots=True, frozen=True)
class StableLeaderboardSelection:
    """Stable client の leaderboard selection を正規化した value object.

    Attributes:
        category (LeaderboardCategory | None): 選択された leaderboard category.
            未対応の category ではNone.
        selected_mods (ModCombination | None): Selected Mods で完全一致に使う canonical mod 組合せ.
            他 category ではNone.
        header_only (bool): score 行を返さず header だけを返す場合はTrue.
        unsupported (bool): 未対応の category または mod 指定を検出した場合はTrue.
    """

    category: LeaderboardCategory | None
    selected_mods: ModCombination | None
    header_only: bool
    unsupported: bool = False


@dataclass(slots=True, frozen=True)
class GetscoresRequest:
    """Stable getscores query を正規化した request value object.

    Attributes:
        checksum_md5 (str | None): beatmap を識別する MD5 checksum. 未指定時はNone.
        filename (str | None): beatmap file name. 未指定時はNone.
        beatmapset_id_hint (int | None): caller が渡した beatmapset ID hint. 未指定時はNone.
        mode (int | None): caller が渡した Stable Mode wire 値. 未指定時はNone.
        mods (int | None): caller が渡した legacy mod bitmask. 未指定時はNone.
        leaderboard_type (int | None): caller が渡した leaderboard type. 未指定時はNone.
        leaderboard_version (int | None): caller が渡した leaderboard version. 未指定時はNone.
        song_select (bool | None): song-select request flag. 未指定時はNone.
        leaderboard_selection (StableLeaderboardSelection | None): 正規化済み selection.
            解釈できない場合はNone.
        anti_cheat_signal (bool): anti-cheat signal が検出された場合はTrue.
        parse_warnings (tuple[GetscoresParseWarning, ...]): 無視した入力値の warning 群.
    """

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
    """Getscores parse の成功 request または失敗理由を表す value object.

    Attributes:
        request (GetscoresRequest | None): parse 成功時に生成した normalized request.
            parse 失敗時はNone.
        error (GetscoresParseError | None): parse 失敗理由. 成功時はNone.
    """

    request: GetscoresRequest | None = None
    error: GetscoresParseError | None = None


class GetscoresOutcomeKind(Enum):
    """Stable getscores が返す高水準 response 種別を表す enum.

    Attributes:
        HEADER (GetscoresOutcomeKind): beatmap header を返す response.
        UNAVAILABLE (GetscoresOutcomeKind): score 表示を利用できない response.
        UPDATE_AVAILABLE (GetscoresOutcomeKind): client update を要求する response.
    """

    HEADER = "header"
    UNAVAILABLE = "unavailable"
    UPDATE_AVAILABLE = "update_available"


class GetscoresResolveReason(Enum):
    """Getscores resolve outcome になった理由を表す enum.

    Attributes:
        KNOWN_CHECKSUM (GetscoresResolveReason): 既知 checksum で beatmap を解決した理由.
        KNOWN_FILENAME_IN_SET (GetscoresResolveReason): beatmapset 内の既知 filename で
            解決した理由.
        NOT_SUBMITTED (GetscoresResolveReason): beatmap は解決したが score が未提出の理由.
        NOT_FOUND (GetscoresResolveReason): beatmap を見つけられなかった理由.
        PENDING_FETCH (GetscoresResolveReason): metadata fetch の完了待ちである理由.
        FAILED_METADATA (GetscoresResolveReason): metadata 解決が失敗した理由.
        UPDATE_AVAILABLE (GetscoresResolveReason): client update が必要な理由.
    """

    KNOWN_CHECKSUM = "known_checksum"
    KNOWN_FILENAME_IN_SET = "known_filename_in_set"
    NOT_SUBMITTED = "not_submitted"
    NOT_FOUND = "not_found"
    PENDING_FETCH = "pending_fetch"
    FAILED_METADATA = "failed_metadata"
    UPDATE_AVAILABLE = "update_available"


@dataclass(slots=True, frozen=True)
class GetscoresPersonalBest:
    """Stable personal-best 欄へそのまま写せる score display value を表す value object.

    Attributes:
        score_id (int): score の永続 ID.
        user_id (int): score を提出した user ID.
        username (str): score を提出した表示 user name.
        beatmap_id (int): score 対象 beatmap の ID.
        ruleset (Ruleset): score の canonical ruleset.
        playstyle (Playstyle): score の canonical playstyle.
        score (int): Stable response に表示する score 値.
        max_combo (int): score の最大 combo.
        n50 (int): 50 hit count.
        n100 (int): 100 hit count.
        n300 (int): 300 hit count.
        miss (int): miss count.
        katu (int): katu count.
        geki (int): geki count.
        perfect (bool): full combo として扱う場合はTrue.
        mods (int): Stable response に表示する legacy mod bitmask.
        rank (int): leaderboard 上の rank.
        submitted_at (datetime): score 提出時刻.
        has_replay (bool): replay が利用可能な場合はTrue.
    """

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
    """Beatmap header と leaderboard row をまとめた解決済み display value を表す value object.

    Attributes:
        beatmap (Beatmap): response header に使う解決済み beatmap.
        beatmapset (BeatmapSet): beatmap が属する解決済み beatmapset.
        personal_best (GetscoresPersonalBest | None): request user の personal best.
            存在しない場合はNone.
        score_rows (tuple[GetscoresPersonalBest, ...]): leaderboard に表示する score row 群.
    """

    beatmap: Beatmap
    beatmapset: BeatmapSet
    personal_best: GetscoresPersonalBest | None = None
    score_rows: tuple[GetscoresPersonalBest, ...] = ()


@dataclass(slots=True, frozen=True)
class GetscoresResolveOutcome:
    """Getscores query が response builder へ渡す resolve outcome を表す value object.

    Attributes:
        kind (GetscoresOutcomeKind): response の高水準種別.
        header (GetscoresResolvedHeader | None): HEADER response に使う display data.
            他 kind ではNone.
        reason (GetscoresResolveReason): outcome になった理由.
    """

    kind: GetscoresOutcomeKind
    header: GetscoresResolvedHeader | None
    reason: GetscoresResolveReason
