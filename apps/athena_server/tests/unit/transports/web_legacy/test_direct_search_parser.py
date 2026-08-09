"""Stable osu!direct search query parserの契約を検証するmodule."""

from osu_server.domain.beatmaps import (
    BeatmapMode,
    BeatmapRankStatus,
    DirectPointLookupTargetKind,
    DirectSearchListing,
)
from osu_server.transports.stable.web_legacy.mappers import (
    StableDirectPointLookupParseError,
    StableDirectPointLookupQueryParser,
    StableDirectSearchParseError,
    StableDirectSearchQueryParser,
)


def test_direct_search_parser_builds_authenticated_typed_request() -> None:
    """Stable direct検索queryを認証済みuser付きrequestへ変換する契約を検証する.

    Returns:
        None: q/r/m/pがdomain requestのtext, status, mode, pageへ写ることを確認する.
    """
    result = StableDirectSearchQueryParser().parse(
        {
            "u": "Player",
            "h": "password-md5",
            "q": "camellia",
            "r": "0",
            "m": "0",
            "p": "2",
        },
        authenticated_user_id=42,
    )

    assert result.error is None
    assert result.request is not None
    assert result.request.authenticated_user_id == 42
    assert result.request.query_text == "camellia"
    assert result.request.statuses == (BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED)
    assert result.request.mode is BeatmapMode.OSU
    assert result.request.page == 2
    assert result.request.page_size == 100
    assert result.request.listing is DirectSearchListing.SEARCH


def test_direct_search_parser_accepts_all_status_and_all_mode_defaults() -> None:
    """Stable directのall status/all modeを検索filterなしとして解析する契約を検証する.

    Returns:
        None: r=4とm=-1がstatus/mode filterを作らないことを確認する.
    """
    result = StableDirectSearchQueryParser().parse(
        {"q": "", "r": "4", "m": "-1"},
        authenticated_user_id=42,
    )

    assert result.error is None
    assert result.request is not None
    assert result.request.query_text == ""
    assert result.request.statuses == ()
    assert result.request.mode is None
    assert result.request.page == 0


def test_direct_search_parser_recognizes_stable_special_listings() -> None:
    """Stable directのspecial queryをliteral text検索ではないlistingとして解析する.

    Returns:
        None: Newest, Top Rated, Most Playedがlisting種別へ変換されることを確認する.
    """
    parser = StableDirectSearchQueryParser()

    newest = parser.parse({"q": "Newest"}, authenticated_user_id=42)
    top_rated = parser.parse({"q": "Top+Rated"}, authenticated_user_id=42)
    most_played = parser.parse({"q": "Most Played"}, authenticated_user_id=42)

    assert newest.request is not None
    assert top_rated.request is not None
    assert most_played.request is not None
    assert newest.request.listing is DirectSearchListing.NEWEST
    assert top_rated.request.listing is DirectSearchListing.TOP_RATED
    assert most_played.request.listing is DirectSearchListing.MOST_PLAYED


def test_direct_search_parser_returns_sanitized_error_without_credentials() -> None:
    """Malformed queryがcredentialを含まないparse errorだけを返す契約を検証する.

    Returns:
        None: u/hやraw password hashがresult reprへ残らないことを確認する.
    """
    result = StableDirectSearchQueryParser().parse(
        {"u": "Player", "h": "secret-hash", "r": "ranked"},
        authenticated_user_id=42,
    )

    assert result.request is None
    assert result.error is StableDirectSearchParseError.MALFORMED_STATUS
    assert "Player" not in repr(result)
    assert "secret-hash" not in repr(result)


def test_direct_point_lookup_parser_builds_supported_targets() -> None:
    """Stable point lookup queryをs,b,cのtarget別requestへ変換する契約を検証する.

    Returns:
        None: beatmapset ID, beatmap ID, checksumがdomain requestへ写ることを確認する.
    """
    parser = StableDirectPointLookupQueryParser()

    by_set = parser.parse({"s": "123"}, authenticated_user_id=42)
    by_beatmap = parser.parse({"b": "456"}, authenticated_user_id=42)
    by_checksum = parser.parse(
        {"c": "ABCDEF0123456789ABCDEF0123456789"},
        authenticated_user_id=42,
    )

    assert by_set.request is not None
    assert by_beatmap.request is not None
    assert by_checksum.request is not None
    assert by_set.request.target_kind is DirectPointLookupTargetKind.BEATMAPSET_ID
    assert by_set.request.target_value == 123
    assert by_beatmap.request.target_kind is DirectPointLookupTargetKind.BEATMAP_ID
    assert by_beatmap.request.target_value == 456
    assert by_checksum.request.target_kind is DirectPointLookupTargetKind.CHECKSUM
    assert by_checksum.request.target_value == "abcdef0123456789abcdef0123456789"


def test_direct_point_lookup_parser_returns_sanitized_error_without_credentials() -> None:
    """Malformed point lookupがcredentialを含まないparse errorだけを返す契約を検証する.

    Returns:
        None: target未指定と不正IDがsanitize済みerrorになりcredentialを保持しないことを確認する.
    """
    parser = StableDirectPointLookupQueryParser()

    missing = parser.parse({"u": "Player", "h": "secret-hash"}, authenticated_user_id=42)
    malformed = parser.parse(
        {"u": "Player", "h": "secret-hash", "s": "not-id"},
        authenticated_user_id=42,
    )

    assert missing.request is None
    assert malformed.request is None
    assert missing.error is StableDirectPointLookupParseError.MISSING_TARGET
    assert malformed.error is StableDirectPointLookupParseError.MALFORMED_TARGET
    assert "Player" not in repr(missing)
    assert "secret-hash" not in repr(malformed)
