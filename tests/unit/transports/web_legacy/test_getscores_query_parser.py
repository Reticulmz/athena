"""GetscoresQueryParser unit tests.

TDD RED -> GREEN -> REFACTOR.
Validates stable getscores query parsing: identity fields, parse-only controls,
parse warnings, and error outcomes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

from athena_cli.stable_verification.getscores_evidence import (
    GetscoresEvidenceStatus,
    load_getscores_completion_evidence,
)
from osu_server.domain.compatibility.stable.getscores import (
    GetscoresParseError,
    GetscoresParseResult,
)
from osu_server.transports.stable.web_legacy.mappers import GetscoresQueryParser
from tests.support.getscores_contract import build_getscores_contract_query

_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures"
_MANIFEST_ROOT = _FIXTURE_ROOT / "stable_compatibility" / "getscores"
_BODY_ROOT = _FIXTURE_ROOT / "web_legacy" / "getscores" / "completion"
_GETSCORES_EVIDENCE = load_getscores_completion_evidence(_MANIFEST_ROOT, _BODY_ROOT)
_GETSCORES_CASES = {case.case_id: case for case in _GETSCORES_EVIDENCE.branch_cases}
_MALFORMED_CASE_IDS = (
    "malformed-mode",
    "malformed-mods",
    "malformed-leaderboard-type",
    "malformed-leaderboard-version",
    "malformed-song-select-flag",
    "malformed-anti-cheat-signal",
    "malformed-beatmapset-hint",
    "malformed-multiple-optional-fields",
)
_INVARIANCE_CONTROL_CASE_IDS = (
    "valid-anti-cheat-signal-invariant",
    "request-version-variant-invariant",
)


def _parse(query: dict[str, str]) -> GetscoresParseResult:
    parser = GetscoresQueryParser()
    return parser.parse(cast("Mapping[str, str]", query))


def _contract_base_query() -> dict[str, str]:
    """Catalog comparison用のsynthetic queryを返す。

    Returns:
        dict[str, str]: Valid identityとsynthetic credentialを持つ新規query。
    """
    return {
        "c": "0123456789abcdef0123456789abcdef",
        "us": "SyntheticViewer",
        "ha": "b" * 32,
    }


# ---------------------------------------------------------------------------
# Identity fields (requirements 3.1, 3.2, 3.3)
# ---------------------------------------------------------------------------


def test_parses_all_identity_fields_from_query() -> None:
    """c, f, and i are preserved as checksum_md5, filename, beatmapset_id_hint."""
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "f": "beatmap.osu",
            "i": "123",
        }
    )

    assert result.error is None
    assert result.request is not None
    assert result.request.checksum_md5 == "0123456789abcdef0123456789abcdef"
    assert result.request.filename == "beatmap.osu"
    assert result.request.beatmapset_id_hint == 123


def test_i_is_treated_as_beatmapset_id_hint_not_beatmap_id() -> None:
    """i is preserved as beatmapset_id_hint (requirement 3.3)."""
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "i": "999",
        }
    )

    assert result.request is not None
    assert result.request.beatmapset_id_hint == 999


# ---------------------------------------------------------------------------
# Parse-only controls (requirements 3.4, 3.5, 3.6, 10.1, 10.2, 10.3, 10.4, 10.5)
# ---------------------------------------------------------------------------


def test_parses_all_parse_only_controls() -> None:
    """m, mods, v, vv, s are preserved as parse-only controls."""
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "m": "3",
            "mods": "64",
            "v": "1",
            "vv": "4",
            "s": "1",
        }
    )

    assert result.request is not None
    assert result.request.mode == 3
    assert result.request.mods == 64
    assert result.request.leaderboard_type == 1
    assert result.request.leaderboard_version == 4
    assert result.request.song_select is True


def test_parse_only_controls_default_to_none_when_absent() -> None:
    """Absent parse-only controls default to None."""
    result = _parse({"c": "0123456789abcdef0123456789abcdef"})

    assert result.request is not None
    assert result.request.mode is None
    assert result.request.mods is None
    assert result.request.leaderboard_type is None
    assert result.request.leaderboard_version is None
    assert result.request.song_select is None


def test_song_select_is_true_only_when_s_is_1() -> None:
    """s=0 maps to song_select=False, s=absent maps to None."""
    r1 = _parse({"c": "0123456789abcdef0123456789abcdef", "s": "1"})
    assert r1.request is not None
    assert r1.request.song_select is True

    r2 = _parse({"c": "0123456789abcdef0123456789abcdef", "s": "0"})
    assert r2.request is not None
    assert r2.request.song_select is False

    r3 = _parse({"c": "0123456789abcdef0123456789abcdef"})
    assert r3.request is not None
    assert r3.request.song_select is None


# ---------------------------------------------------------------------------
# Anti-cheat signal (requirement 3.7, 12.1)
# ---------------------------------------------------------------------------


def test_anti_cheat_signal_is_true_for_one_without_warning() -> None:
    """`a=1`をwarningなしのanti-cheat signalとして解析する。

    Returns:
        None: SignalがTrueでwarningが空であることを示す。
    """
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "a": "1",
        }
    )

    assert result.request is not None
    assert result.request.anti_cheat_signal is True
    assert result.request.parse_warnings == ()


def test_anti_cheat_signal_is_false_for_zero_without_warning() -> None:
    """`a=0`をwarningなしのfalse signalとして解析する。

    Returns:
        None: SignalがFalseでwarningが空であることを示す。
    """
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "a": "0",
        }
    )

    assert result.request is not None
    assert result.request.anti_cheat_signal is False
    assert result.request.parse_warnings == ()


def test_anti_cheat_signal_is_false_when_a_absent() -> None:
    """Anti-cheat signal is False when a query param is absent."""
    result = _parse({"c": "0123456789abcdef0123456789abcdef"})

    assert result.request is not None
    assert result.request.anti_cheat_signal is False


# ---------------------------------------------------------------------------
# Identity sufficiency (requirement 3.9)
# ---------------------------------------------------------------------------


def test_checksum_alone_is_sufficient_identity() -> None:
    """Checksum alone provides sufficient identity."""
    result = _parse({"c": "0123456789abcdef0123456789abcdef"})

    assert result.error is None
    assert result.request is not None


def test_filename_plus_beatmapset_id_is_sufficient_identity() -> None:
    """Filename plus beatmapset id hint provides sufficient identity."""
    result = _parse({"f": "beatmap.osu", "i": "123"})

    assert result.error is None
    assert result.request is not None
    assert result.request.checksum_md5 is None
    assert result.request.filename == "beatmap.osu"
    assert result.request.beatmapset_id_hint == 123


def test_filename_alone_is_insufficient_identity() -> None:
    """Filename without beatmapset id hint is insufficient (requirement 4.4, 4.6)."""
    result = _parse({"f": "beatmap.osu"})

    assert result.request is None
    assert result.error is GetscoresParseError.MISSING_IDENTITY


def test_beatmapset_id_alone_is_insufficient_identity() -> None:
    """Beatmapset id hint without filename is insufficient (requirement 4.4)."""
    result = _parse({"i": "123"})

    assert result.request is None
    assert result.error is GetscoresParseError.MISSING_IDENTITY


def test_no_identity_fields_returns_missing_identity() -> None:
    """Empty query or no identity fields returns missing_identity error."""
    result = _parse({})

    assert result.request is None
    assert result.error is GetscoresParseError.MISSING_IDENTITY


# ---------------------------------------------------------------------------
# Invalid checksum (invalid_checksum error)
# ---------------------------------------------------------------------------


def test_invalid_checksum_format_returns_invalid_checksum_error() -> None:
    """Non-hex or non-32-char checksum returns invalid_checksum error."""
    result = _parse({"c": "not-a-valid-md5"})

    assert result.request is None
    assert result.error is GetscoresParseError.INVALID_CHECKSUM


def test_short_checksum_returns_invalid_checksum_error() -> None:
    """Too-short checksum returns invalid_checksum error."""
    result = _parse({"c": "abc"})

    assert result.request is None
    assert result.error is GetscoresParseError.INVALID_CHECKSUM


# ---------------------------------------------------------------------------
# Malformed non-identity fields → warnings (requirement 3.8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", _MALFORMED_CASE_IDS)
def test_malformed_catalog_case_produces_exact_provisional_warning_set(
    case_id: str,
) -> None:
    """Malformed catalog caseをparserのexact warning集合へ照合する。

    Args:
        case_id (str): Canonical malformed branch case ID。

    Returns:
        None: Warning集合とprovisional evidence stateが一致したことを示す。

    Raises:
        KeyError: Canonical branch caseがtyped evidence bundleに存在しない場合。
        AssertionError: Runtime warning集合がcatalog contractと異なる場合。
    """
    case = _GETSCORES_CASES[case_id]
    query = build_getscores_contract_query(case, _contract_base_query())

    result = _parse(query)

    assert case.evidence_status is GetscoresEvidenceStatus.PROVISIONAL_ATHENA_BEHAVIOR
    assert result.error is None
    assert result.request is not None
    actual_warnings = result.request.parse_warnings
    assert len(actual_warnings) == len(case.expected_warning_categories)
    assert frozenset(actual_warnings) == frozenset(case.expected_warning_categories)
    if case_id == "malformed-anti-cheat-signal":
        assert result.request.anti_cheat_signal is False


@pytest.mark.parametrize("case_id", _INVARIANCE_CONTROL_CASE_IDS)
def test_diagnostic_control_case_preserves_empty_warning_contract(case_id: str) -> None:
    """Valid diagnostic variantがwarningを追加しないことを確認する。

    Args:
        case_id (str): Canonical invariance control case ID。

    Returns:
        None: Empty warningとAthena deterministic stateが一致したことを示す。

    Raises:
        KeyError: Canonical branch caseがtyped evidence bundleに存在しない場合。
        AssertionError: Runtime parse resultがcatalog contractと異なる場合。
    """
    case = _GETSCORES_CASES[case_id]
    query = build_getscores_contract_query(case, _contract_base_query())

    result = _parse(query)

    assert case.evidence_status is GetscoresEvidenceStatus.ATHENA_DETERMINISTIC
    assert case.expected_warning_categories == ()
    assert result.error is None
    assert result.request is not None
    assert result.request.parse_warnings == ()
    if case_id == "valid-anti-cheat-signal-invariant":
        assert result.request.anti_cheat_signal is True
    else:
        assert result.request.leaderboard_version == 5


# ---------------------------------------------------------------------------
# Interface contract
# ---------------------------------------------------------------------------


def test_parser_has_expected_interface() -> None:
    """GetscoresQueryParser has the expected parse method."""
    parser = GetscoresQueryParser()
    assert hasattr(parser, "parse")
    assert callable(parser.parse)


def test_parse_result_provides_either_request_or_error_not_both() -> None:
    """Successful parse has request and no error; failed parse has error and no request."""
    success = _parse({"c": "0123456789abcdef0123456789abcdef"})
    assert success.request is not None
    assert success.error is None

    failure = _parse({})
    assert failure.request is None
    assert failure.error is not None


def test_parse_warnings_can_be_iterated_and_counted() -> None:
    """Parse warnings tuple supports iteration and len()."""
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "m": "bad",
            "mods": "bad",
            "v": "bad",
        }
    )

    assert result.request is not None
    assert len(result.request.parse_warnings) == 3
    assert sum(1 for _ in result.request.parse_warnings) == 3
