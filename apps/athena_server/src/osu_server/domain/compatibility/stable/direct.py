"""Stable osu!direct固有のrequest互換値を定義するmodule."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from osu_server.domain.beatmaps import BeatmapMode, BeatmapRankStatus, DirectSearchListing

STABLE_DIRECT_PAGE_SIZE: Final = 100
STABLE_DIRECT_MORE_RESULTS_SENTINEL: Final = 101

_ALL_STATUS_FILTER = 4
_ALL_MODE_FILTER = -1
_STATUS_FILTERS: Final[dict[int, tuple[BeatmapRankStatus, ...]]] = {
    0: (BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED),
    2: (BeatmapRankStatus.PENDING,),
    3: (BeatmapRankStatus.QUALIFIED,),
    5: (BeatmapRankStatus.GRAVEYARD,),
    7: (BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED),
    8: (BeatmapRankStatus.LOVED,),
}
_MODE_FILTERS: Final[dict[int, BeatmapMode]] = {
    0: BeatmapMode.OSU,
    1: BeatmapMode.TAIKO,
    2: BeatmapMode.FRUITS,
    3: BeatmapMode.MANIA,
}
_SPECIAL_LISTINGS: Final[dict[str, DirectSearchListing]] = {
    "newest": DirectSearchListing.NEWEST,
    "top rated": DirectSearchListing.TOP_RATED,
    "most played": DirectSearchListing.MOST_PLAYED,
}


class StableDirectSearchParseError(StrEnum):
    """Stable osu!direct search queryのsanitize済みparse errorを表す.

    Attributes:
        MALFORMED_STATUS (StableDirectSearchParseError): r fieldを整数として解釈できない.
        MALFORMED_MODE (StableDirectSearchParseError): m fieldを有効なmodeとして解釈できない.
        MALFORMED_PAGE (StableDirectSearchParseError): p fieldを有効なpageとして解釈できない.
    """

    MALFORMED_STATUS = "malformed_status"
    MALFORMED_MODE = "malformed_mode"
    MALFORMED_PAGE = "malformed_page"


def stable_direct_statuses_from_wire(
    raw_status: str | None,
) -> tuple[BeatmapRankStatus, ...] | StableDirectSearchParseError:
    """Stable direct r fieldをdomain status filterへ変換する.

    Args:
        raw_status (str | None): stable clientのr field. 未指定なら全status.

    Returns:
        tuple[BeatmapRankStatus, ...] | StableDirectSearchParseError:
            空tupleは全status, 非空tupleはOR filter, malformed時はsanitize済みerror.
    """
    if raw_status in (None, ""):
        return ()
    try:
        status_value = int(raw_status)
    except ValueError:
        return StableDirectSearchParseError.MALFORMED_STATUS
    if status_value == _ALL_STATUS_FILTER:
        return ()
    return _STATUS_FILTERS.get(status_value, (BeatmapRankStatus.RANKED,))


def stable_direct_mode_from_wire(
    raw_mode: str | None,
) -> BeatmapMode | None | StableDirectSearchParseError:
    """Stable direct m fieldをdomain mode filterへ変換する.

    Args:
        raw_mode (str | None): stable clientのm field. 未指定または-1なら全mode.

    Returns:
        BeatmapMode | None | StableDirectSearchParseError:
            Noneは全mode, BeatmapModeは単一mode filter, malformed時はsanitize済みerror.
    """
    if raw_mode in (None, ""):
        return None
    try:
        mode_value = int(raw_mode)
    except ValueError:
        return StableDirectSearchParseError.MALFORMED_MODE
    if mode_value == _ALL_MODE_FILTER:
        return None
    return _MODE_FILTERS.get(mode_value, StableDirectSearchParseError.MALFORMED_MODE)


def stable_direct_page_from_wire(raw_page: str | None) -> int | StableDirectSearchParseError:
    """Stable direct p fieldを0始まりpage番号へ変換する.

    Args:
        raw_page (str | None): stable clientのp field. 未指定なら0.

    Returns:
        int | StableDirectSearchParseError: 0以上のpage番号. malformed時はsanitize済みerror.
    """
    if raw_page in (None, ""):
        return 0
    try:
        page = int(raw_page)
    except ValueError:
        return StableDirectSearchParseError.MALFORMED_PAGE
    if page < 0:
        return StableDirectSearchParseError.MALFORMED_PAGE
    return page


def stable_direct_listing_from_query(query_text: str) -> tuple[str, DirectSearchListing]:
    """Stable direct q fieldから検索文字列とlisting種別を返す.

    Args:
        query_text (str): stable clientのq field. URL未decodeの`+`も空白として扱う.

    Returns:
        tuple[str, DirectSearchListing]: backendへ渡すquery textとlisting種別.
    """
    normalized = query_text.replace("+", " ").strip()
    listing = _SPECIAL_LISTINGS.get(normalized.casefold())
    if listing is not None:
        return ("", listing)
    return (normalized, DirectSearchListing.SEARCH)


__all__ = [
    "STABLE_DIRECT_MORE_RESULTS_SENTINEL",
    "STABLE_DIRECT_PAGE_SIZE",
    "StableDirectSearchParseError",
    "stable_direct_listing_from_query",
    "stable_direct_mode_from_wire",
    "stable_direct_page_from_wire",
    "stable_direct_statuses_from_wire",
]
