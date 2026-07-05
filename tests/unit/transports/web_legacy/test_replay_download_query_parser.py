"""Replay download query parser tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from osu_server.domain.compatibility.stable import ReplayDownloadBranch
from osu_server.domain.scores.score import Ruleset
from osu_server.transports.stable.web_legacy.mappers import (
    ReplayDownloadMalformedReason,
    ReplayDownloadParseResult,
    ReplayDownloadQueryParser,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


_RAW_USERNAME = "SYNTHETIC_RAW_REPLAY_DOWNLOAD_USERNAME"
_RAW_PASSWORD_HASH = "SYNTHETIC_RAW_REPLAY_DOWNLOAD_HASH"
_RAW_SCORE_ID = "8675309"
_RAW_MODE = "3"


def _parse(query: dict[str, str]) -> ReplayDownloadParseResult:
    parser = ReplayDownloadQueryParser()
    return parser.parse(cast("Mapping[str, str]", query))


def _assert_valid_request(
    result: ReplayDownloadParseResult,
    *,
    expected_score_id: int,
    expected_ruleset: Ruleset,
) -> None:
    if result.request is None:
        raise AssertionError("parser did not return a request")
    if result.request.score_id != expected_score_id:
        raise AssertionError("score id did not parse")
    if result.request.ruleset is not expected_ruleset:
        raise AssertionError("ruleset did not parse")
    if result.branch is not None:
        raise AssertionError("valid request unexpectedly had a fallback branch")
    if result.reason is not None:
        raise AssertionError("valid request unexpectedly had a fallback reason")


def _assert_malformed(
    result: ReplayDownloadParseResult,
    reason: ReplayDownloadMalformedReason,
) -> None:
    if result.request is not None:
        raise AssertionError("malformed request unexpectedly returned typed request")
    if result.branch is not ReplayDownloadBranch.MALFORMED_REQUEST_PROVISIONAL:
        raise AssertionError("malformed request did not use provisional fallback branch")
    if result.reason is not reason:
        raise AssertionError("malformed request used the wrong sanitized reason")


def _assert_raw_values_not_rendered(
    result: ReplayDownloadParseResult,
    raw_values: Iterable[str],
) -> None:
    rendered = f"{result!s} {result!r}"
    if result.request is not None:
        rendered = f"{rendered} {result.request!r}"

    for raw_value in raw_values:
        if raw_value in rendered:
            raise AssertionError("parser result rendered a raw query value")


def test_parses_confirmed_score_id_and_ruleset_without_auth_values() -> None:
    query = {
        "c": _RAW_SCORE_ID,
        "m": _RAW_MODE,
        "u": _RAW_USERNAME,
        "h": _RAW_PASSWORD_HASH,
    }

    result = _parse(query)

    _assert_valid_request(
        result,
        expected_score_id=8675309,
        expected_ruleset=Ruleset.MANIA,
    )
    _assert_raw_values_not_rendered(result, query.values())


def test_missing_score_id_is_provisional_malformed_fallback() -> None:
    query = {
        "m": "0",
        "u": _RAW_USERNAME,
        "h": _RAW_PASSWORD_HASH,
    }

    result = _parse(query)

    _assert_malformed(result, ReplayDownloadMalformedReason.MISSING_SCORE_ID)
    _assert_raw_values_not_rendered(result, query.values())


def test_malformed_score_id_is_provisional_malformed_fallback() -> None:
    query = {
        "c": "SYNTHETIC_RAW_SCORE_ID",
        "m": "0",
        "u": _RAW_USERNAME,
        "h": _RAW_PASSWORD_HASH,
    }

    result = _parse(query)

    _assert_malformed(result, ReplayDownloadMalformedReason.MALFORMED_SCORE_ID)
    _assert_raw_values_not_rendered(result, query.values())


def test_missing_ruleset_is_provisional_malformed_fallback() -> None:
    query = {
        "c": _RAW_SCORE_ID,
        "u": _RAW_USERNAME,
        "h": _RAW_PASSWORD_HASH,
    }

    result = _parse(query)

    _assert_malformed(result, ReplayDownloadMalformedReason.MISSING_MODE)
    _assert_raw_values_not_rendered(result, query.values())


def test_malformed_ruleset_is_provisional_malformed_fallback() -> None:
    query = {
        "c": _RAW_SCORE_ID,
        "m": "SYNTHETIC_RAW_MODE",
        "u": _RAW_USERNAME,
        "h": _RAW_PASSWORD_HASH,
    }

    result = _parse(query)

    _assert_malformed(result, ReplayDownloadMalformedReason.MALFORMED_MODE)
    _assert_raw_values_not_rendered(result, query.values())


def test_unknown_ruleset_is_provisional_malformed_fallback() -> None:
    query = {
        "c": _RAW_SCORE_ID,
        "m": "99",
        "u": _RAW_USERNAME,
        "h": _RAW_PASSWORD_HASH,
    }

    result = _parse(query)

    _assert_malformed(result, ReplayDownloadMalformedReason.MALFORMED_MODE)
    _assert_raw_values_not_rendered(result, query.values())


def test_unknown_query_field_is_provisional_malformed_fallback() -> None:
    query = {
        "c": _RAW_SCORE_ID,
        "m": "0",
        "u": _RAW_USERNAME,
        "h": _RAW_PASSWORD_HASH,
        "unexpected": "SYNTHETIC_RAW_UNKNOWN_VALUE",
    }

    result = _parse(query)

    _assert_malformed(result, ReplayDownloadMalformedReason.UNKNOWN_FIELD)
    _assert_raw_values_not_rendered(result, query.values())
