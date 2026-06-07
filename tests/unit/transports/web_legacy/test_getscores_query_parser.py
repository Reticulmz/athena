"""GetscoresQueryParser unit tests.

TDD RED -> GREEN -> REFACTOR.
Validates stable getscores query parsing: identity fields, parse-only controls,
parse warnings, and error outcomes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

from osu_server.transports.web_legacy.getscores_query_parser import (
    GetscoresParseError,
    GetscoresParseResult,
    GetscoresParseWarning,
    GetscoresQueryParser,
)


def _parse(query: dict[str, str]) -> GetscoresParseResult:
    parser = GetscoresQueryParser()
    return parser.parse(cast("Mapping[str, str]", query))


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


def test_anti_cheat_signal_is_true_when_a_present() -> None:
    """Anti-cheat signal is True when a query param is present (requirement 3.7)."""
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "a": "1",
        }
    )

    assert result.request is not None
    assert result.request.anti_cheat_signal is True


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


def test_malformed_mode_produces_warning_with_valid_identity() -> None:
    """Non-integer m produces invalid_mode warning, still returns request."""
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "m": "not_an_int",
        }
    )

    assert result.error is None
    assert result.request is not None
    assert GetscoresParseWarning.INVALID_MODE in result.request.parse_warnings


def test_malformed_mods_produces_warning() -> None:
    """Non-integer mods produces invalid_mods warning."""
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "mods": "abc",
        }
    )

    assert result.request is not None
    assert GetscoresParseWarning.INVALID_MODS in result.request.parse_warnings


def test_malformed_leaderboard_type_produces_warning() -> None:
    """Non-integer v produces invalid_leaderboard_type warning."""
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "v": "xxx",
        }
    )

    assert result.request is not None
    assert GetscoresParseWarning.INVALID_LEADERBOARD_TYPE in result.request.parse_warnings


def test_malformed_leaderboard_version_produces_warning() -> None:
    """Non-integer vv produces invalid_leaderboard_version warning."""
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "vv": "abc",
        }
    )

    assert result.request is not None
    assert GetscoresParseWarning.INVALID_LEADERBOARD_VERSION in result.request.parse_warnings


def test_malformed_song_select_produces_warning() -> None:
    """Non-integer s produces invalid_song_select_flag warning."""
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "s": "yes",
        }
    )

    assert result.request is not None
    assert GetscoresParseWarning.INVALID_SONG_SELECT_FLAG in result.request.parse_warnings


def test_malformed_beatmapset_id_hint_produces_warning_with_other_identity() -> None:
    """Non-integer i with valid checksum produces warning, not error."""
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "i": "abc",
        }
    )

    assert result.error is None
    assert result.request is not None
    assert GetscoresParseWarning.INVALID_BEATMAPSET_ID_HINT in result.request.parse_warnings


def test_multiple_malformed_fields_produce_multiple_warnings() -> None:
    """Multiple non-identity parse failures each produce a warning."""
    result = _parse(
        {
            "c": "0123456789abcdef0123456789abcdef",
            "m": "bad",
            "mods": "also_bad",
        }
    )

    assert result.request is not None
    warnings = result.request.parse_warnings
    assert GetscoresParseWarning.INVALID_MODE in warnings
    assert GetscoresParseWarning.INVALID_MODS in warnings


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
