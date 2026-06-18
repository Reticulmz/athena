"""Stable legacy getscores query and response mappers."""

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
from osu_server.domain.scores.leaderboards import filter_from_mod_combination
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
    if raw is None:
        return None
    try:
        return bool(int(raw))
    except ValueError:
        warnings.append(warning_kind)
        return None


class GetscoresQueryParser:
    """Map stable legacy getscores query parameters to a query input value."""

    def parse(self, query: Mapping[str, str]) -> GetscoresParseResult:
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
            anti_cheat_signal="a" in query,
            parse_warnings=tuple(warnings),
        )
        selection = StableGetscoresLeaderboardMapper().map_request(request)

        return GetscoresParseResult(request=replace(request, leaderboard_selection=selection))


class StableGetscoresLeaderboardMapper:
    """Map stable getscores category fields to leaderboard query selection."""

    def map_request(self, request: GetscoresRequest) -> StableLeaderboardSelection:
        category = _leaderboard_category_from_request(request)
        if category is None:
            return StableLeaderboardSelection(
                category=None,
                selected_mod_filter=None,
                header_only=True,
                unsupported=request.leaderboard_type is not None,
            )

        mods = _mods_from_request(request)
        if mods is None:
            return StableLeaderboardSelection(
                category=category,
                selected_mod_filter=None,
                header_only=True,
                unsupported=True,
            )

        if mods.has(Mod.RELAX) or mods.has(Mod.AUTOPILOT):
            return StableLeaderboardSelection(
                category=category,
                selected_mod_filter=None,
                header_only=True,
            )

        selected_mod_filter = None
        unsupported = False
        if category is LeaderboardCategory.SELECTED_MODS:
            selected_mod_filter = filter_from_mod_combination(mods)
            unsupported = not selected_mod_filter.is_supported

        return StableLeaderboardSelection(
            category=category,
            selected_mod_filter=selected_mod_filter,
            header_only=request.song_select is True or unsupported,
            unsupported=unsupported,
        )


class GetscoresStatusMapper:
    """Map beatmap rank status to stable legacy getscores wire status."""

    def map_header_status(self, beatmap: Beatmap) -> int | None:
        return _STATUS_TO_WIRE.get(beatmap.effective_status)


def _leaderboard_category_from_request(
    request: GetscoresRequest,
) -> LeaderboardCategory | None:
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
    try:
        return stable_mod_bitmask_to_mod_combination(request.mods or 0)
    except ValueError:
        return None
