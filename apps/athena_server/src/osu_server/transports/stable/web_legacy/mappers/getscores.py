"""安定版 legacy getscores のqueryとresponseを変換する."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.compatibility.stable.getscores import (
    GetscoresParseError,
    GetscoresParseResult,
    GetscoresParseWarning,
    GetscoresRequest,
    StableLeaderboardSelection,
)
from osu_server.domain.compatibility.stable.mods import stable_mod_bitmask_to_mod_combination
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.personal_best import LeaderboardCategory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from osu_server.domain.beatmaps import Beatmap

_MD5_HEX_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")
_STATUS_TO_WIRE: dict[BeatmapRankStatus, int | None] = {
    BeatmapRankStatus.NOT_SUBMITTED: None,
    BeatmapRankStatus.UNKNOWN: None,
    BeatmapRankStatus.PENDING: 0,
    BeatmapRankStatus.WIP: 0,
    BeatmapRankStatus.GRAVEYARD: 0,
    BeatmapRankStatus.RANKED: 2,
    BeatmapRankStatus.APPROVED: 3,
    BeatmapRankStatus.QUALIFIED: 4,
    BeatmapRankStatus.LOVED: 5,
}
_LOCAL_LEADERBOARD_TYPE = 1
_SELECTED_MODS_LEADERBOARD_TYPE = 2
_FRIENDS_LEADERBOARD_TYPE = 3
_COUNTRY_LEADERBOARD_TYPE = 4


def _parse_int(
    raw: str | None,
    warnings: list[GetscoresParseWarning],
    warning_kind: GetscoresParseWarning,
) -> int | None:
    """任意のquery文字列を整数へ変換し, 失敗をwarningへ記録する.

    Args:
        raw (str | None): 整数として解釈するquery値.
        warnings (list[GetscoresParseWarning]): 解析失敗を追加するwarningの可変list.
        warning_kind (GetscoresParseWarning): 変換失敗時に追加するwarning種別.

    Returns:
        int | None: 変換した整数. 値がないか整数でない場合はNone.
    """
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        warnings.append(warning_kind)
        return None


def _parse_bool(
    raw: str | None,
    warnings: list[GetscoresParseWarning],
    warning_kind: GetscoresParseWarning,
) -> bool | None:
    """整数表現のquery値をboolへ変換し, 失敗をwarningへ記録する.

    Args:
        raw (str | None): 0または非0の整数として解釈するquery値.
        warnings (list[GetscoresParseWarning]): 解析失敗を追加するwarningの可変list.
        warning_kind (GetscoresParseWarning): 変換失敗時に追加するwarning種別.

    Returns:
        bool | None: 整数の真偽値. 値がないか整数でない場合はNone.
    """
    if raw is None:
        return None
    try:
        return bool(int(raw))
    except ValueError:
        warnings.append(warning_kind)
        return None


class GetscoresQueryParser:
    """安定版 legacy getscoresのquery parameterをquery inputへ変換する."""

    def parse(self, query: Mapping[str, str]) -> GetscoresParseResult:
        """Stable getscores queryをtyped parse resultへ変換する.

        Args:
            query (Mapping[str, str]): Stable clientから受け取ったquery fieldのmapping.

        Returns:
            GetscoresParseResult: 正常時は正規化済みrequestを持つresult. Checksumが
            不正な場合またはbeatmap identityが不足する場合はerrorを持つ.
            Optional fieldがmalformedな場合はwarningとdeterministic fallbackを
            requestへ保持する.

        Notes:
            Malformedなoptional fieldは例外を送出せずwarningへ変換する. `a`は
            integer-backed booleanとして解析し, `0`はFalse, nonzero integerは
            True, non-integerは`INVALID_ANTI_CHEAT_SIGNAL` warningとFalse fallbackに
            する. External contractが許容するinteger rangeは制限または断定しない.
        """
        warnings: list[GetscoresParseWarning] = []

        checksum_raw = query.get("c")
        filename = query.get("f") or None
        beatmapset_id_hint = _parse_int(
            query.get("i"),
            warnings,
            GetscoresParseWarning.INVALID_BEATMAPSET_ID_HINT,
        )

        checksum_md5: str | None = None
        if checksum_raw is not None:
            if _MD5_HEX_PATTERN.match(checksum_raw):
                checksum_md5 = checksum_raw.lower()
            else:
                return GetscoresParseResult(error=GetscoresParseError.INVALID_CHECKSUM)

        mode = _parse_int(query.get("m"), warnings, GetscoresParseWarning.INVALID_MODE)
        mods = _parse_int(query.get("mods"), warnings, GetscoresParseWarning.INVALID_MODS)
        leaderboard_type = _parse_int(
            query.get("v"),
            warnings,
            GetscoresParseWarning.INVALID_LEADERBOARD_TYPE,
        )
        leaderboard_version = _parse_int(
            query.get("vv"),
            warnings,
            GetscoresParseWarning.INVALID_LEADERBOARD_VERSION,
        )
        song_select = _parse_bool(
            query.get("s"),
            warnings,
            GetscoresParseWarning.INVALID_SONG_SELECT_FLAG,
        )
        anti_cheat_signal = _parse_bool(
            query.get("a"),
            warnings,
            GetscoresParseWarning.INVALID_ANTI_CHEAT_SIGNAL,
        )

        has_checksum = checksum_md5 is not None
        has_fallback = filename is not None and beatmapset_id_hint is not None
        if not has_checksum and not has_fallback:
            return GetscoresParseResult(error=GetscoresParseError.MISSING_IDENTITY)

        request = GetscoresRequest(
            checksum_md5=checksum_md5,
            filename=filename,
            beatmapset_id_hint=beatmapset_id_hint,
            mode=mode,
            mods=mods,
            leaderboard_type=leaderboard_type,
            leaderboard_version=leaderboard_version,
            song_select=song_select,
            anti_cheat_signal=anti_cheat_signal is True,
            parse_warnings=tuple(warnings),
        )
        selection = StableGetscoresLeaderboardMapper().map_request(request)

        return GetscoresParseResult(request=replace(request, leaderboard_selection=selection))


class StableGetscoresLeaderboardMapper:
    """Stable getscoresのcategory fieldをleaderboard選択へ変換するmapper."""

    def map_request(self, request: GetscoresRequest) -> StableLeaderboardSelection:
        """Getscores requestからleaderboard選択結果を構築する.

        Args:
            request (GetscoresRequest): stable clientから解析したgetscores request.

        Returns:
            StableLeaderboardSelection: category, Selected Modsのraw bitflag,
            header-only状態, および未対応状態を含む選択結果.

        Notes:
            Selected Mods以外では`selected_mods`をNoneにする. Relaxまたは
            Autopilotを含む指定と不正なMod値はscore行を返さない.
        """
        category = _leaderboard_category_from_request(request)
        if category is None:
            return StableLeaderboardSelection(
                category=None,
                selected_mods=None,
                header_only=True,
                unsupported=request.leaderboard_type is not None,
            )

        mods = _mods_from_request(request)
        if mods is None:
            return StableLeaderboardSelection(
                category=category,
                selected_mods=None,
                header_only=True,
                unsupported=True,
            )

        if mods.has(Mod.RELAX) or mods.has(Mod.AUTOPILOT):
            return StableLeaderboardSelection(
                category=category,
                selected_mods=None,
                header_only=True,
            )

        return StableLeaderboardSelection(
            category=category,
            selected_mods=(mods if category is LeaderboardCategory.SELECTED_MODS else None),
            header_only=request.song_select is True,
        )


class GetscoresStatusMapper:
    """Beatmapのrank statusを安定版legacy getscoresのwire statusへ変換する."""

    def map_header_status(self, beatmap: Beatmap) -> int | None:
        """Beatmapのrank statusをheaderで返すwire値へ変換する.

        Args:
            beatmap (Beatmap): rank statusを取得するbeatmap.

        Returns:
            int | None: stable clientへ返すstatus値. scoreを返せないstatusはNone.
        """
        return _STATUS_TO_WIRE.get(beatmap.effective_status)


def _leaderboard_category_from_request(
    request: GetscoresRequest,
) -> LeaderboardCategory | None:
    """Getscoresのleaderboard typeを内部categoryへ変換する.

    Args:
        request (GetscoresRequest): leaderboard typeを含む解析済みrequest.

    Returns:
        LeaderboardCategory | None: 対応するcategory. 未指定または未対応値ではNone.
    """
    if request.leaderboard_type == _LOCAL_LEADERBOARD_TYPE:
        return LeaderboardCategory.GLOBAL
    if request.leaderboard_type == _SELECTED_MODS_LEADERBOARD_TYPE:
        return LeaderboardCategory.SELECTED_MODS
    if request.leaderboard_type == _FRIENDS_LEADERBOARD_TYPE:
        return LeaderboardCategory.FRIENDS
    if request.leaderboard_type == _COUNTRY_LEADERBOARD_TYPE:
        return LeaderboardCategory.COUNTRY
    return None


def _mods_from_request(request: GetscoresRequest) -> ModCombination | None:
    """Getscores requestのmod bitmaskをcanonicalなModCombinationへ変換する.

    Args:
        request (GetscoresRequest): mod bitmaskを含む解析済みrequest.

    Returns:
        ModCombination | None: stable対応済みのmods. 不正または未対応bitではNone.
    """
    try:
        return stable_mod_bitmask_to_mod_combination(request.mods or 0)
    except ValueError:
        return None
