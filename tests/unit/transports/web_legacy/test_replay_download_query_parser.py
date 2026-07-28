"""Replay download query parserのidentity validationとfallback contractを検証する."""

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
    """Legacy replay download query mappingをtyped parser resultへ変換する.

    Args:
        query (dict[str, str]): score ID, mode, credentialを含むquery parameter mapping.

    Returns:
        ReplayDownloadParseResult: typed requestまたはprovisional malformed fallbackを持つresult.
    """
    parser = ReplayDownloadQueryParser()
    return parser.parse(cast("Mapping[str, str]", query))


def _assert_valid_request(
    result: ReplayDownloadParseResult,
    *,
    expected_score_id: int,
    expected_ruleset: Ruleset,
) -> None:
    """Parse resultがexpected score IDとrulesetだけを持つvalid requestか検証する.

    Args:
        result (ReplayDownloadParseResult): valid requestであるべきparser result.
        expected_score_id (int): requestへ期待するnumeric score ID.
        expected_ruleset (Ruleset): requestへ期待するparsed ruleset.

    Returns:
        None: valid requestのfieldとfallback不在の検証を完了する.

    Raises:
        AssertionError: request fieldまたはfallback stateがexpected valueと異なる場合.
    """
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
    """Parse resultがexpected reasonを持つprovisional malformed fallbackか検証する.

    Args:
        result (ReplayDownloadParseResult): malformed requestであるべきparser result.
        reason (ReplayDownloadMalformedReason): expected sanitized malformed reason.

    Returns:
        None: typed request不在とfallback branch, reasonの検証を完了する.

    Raises:
        AssertionError: malformed resultのbranchまたはreasonがexpected valueと異なる場合.
    """
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
    """Parser resultのtext representationがraw query valueを露出しないことを検証する.

    Args:
        result (ReplayDownloadParseResult): representationを検査するparser result.
        raw_values (Iterable[str]): resultへ出力してはならないraw query value群.

    Returns:
        None: raw value leakage検証を完了する.

    Raises:
        AssertionError: raw query valueがstrまたはreprへ含まれる場合.
    """
    rendered = f"{result!s} {result!r}"
    if result.request is not None:
        rendered = f"{rendered} {result.request!r}"

    for raw_value in raw_values:
        if raw_value in rendered:
            raise AssertionError("parser result rendered a raw query value")


def test_parses_confirmed_score_id_and_ruleset_without_auth_values() -> None:
    """Confirmed score IDとrulesetをparseしauth valueをresultへ残さないcontractを検証する.

    Returns:
        None: typed requestのfieldとraw credentialの非露出を確認して完了する.
    """
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
    """Score ID欠落がprovisional malformed fallbackになるcontractを検証する.

    Returns:
        None: MISSING_SCORE_ID reasonとraw credentialの非露出を確認して完了する.
    """
    query = {
        "m": "0",
        "u": _RAW_USERNAME,
        "h": _RAW_PASSWORD_HASH,
    }

    result = _parse(query)

    _assert_malformed(result, ReplayDownloadMalformedReason.MISSING_SCORE_ID)
    _assert_raw_values_not_rendered(result, query.values())


def test_malformed_score_id_is_provisional_malformed_fallback() -> None:
    """Numericでないscore IDがprovisional malformed fallbackになるcontractを検証する.

    Returns:
        None: MALFORMED_SCORE_ID reasonとraw queryの非露出を確認して完了する.
    """
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
    """Mode欠落がprovisional malformed fallbackになるcontractを検証する.

    Returns:
        None: MISSING_MODE reasonとraw credentialの非露出を確認して完了する.
    """
    query = {
        "c": _RAW_SCORE_ID,
        "u": _RAW_USERNAME,
        "h": _RAW_PASSWORD_HASH,
    }

    result = _parse(query)

    _assert_malformed(result, ReplayDownloadMalformedReason.MISSING_MODE)
    _assert_raw_values_not_rendered(result, query.values())


def test_malformed_ruleset_is_provisional_malformed_fallback() -> None:
    """Numericでないmodeがprovisional malformed fallbackになるcontractを検証する.

    Returns:
        None: MALFORMED_MODE reasonとraw queryの非露出を確認して完了する.
    """
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
    """Unsupported mode valueがprovisional malformed fallbackになるcontractを検証する.

    Returns:
        None: MALFORMED_MODE reasonとraw queryの非露出を確認して完了する.
    """
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
    """Unknown query fieldがprovisional malformed fallbackになるcontractを検証する.

    Returns:
        None: UNKNOWN_FIELD reasonとraw queryの非露出を確認して完了する.
    """
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
