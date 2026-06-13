"""Tests for LoginParser (Task 5.1).

Validates:
- Requirement 5.2: parse_login_request splits body into username, password_md5, client_info
- Requirement 5.3: parse_client_info splits pipe-delimited fields with type conversions

Test categories:
- Normal parse: valid login body, valid client_info
- Invalid format: insufficient lines, empty body
- Client info field shortage
- Type conversion edge cases: negative utc_offset, boolean boundaries
"""

from __future__ import annotations

import pytest

from osu_server.domain.identity.authentication import ClientInfo, LoginRequest
from osu_server.transports.bancho.parsers.login import (
    parse_client_info,
    parse_login_request,
)


class TestParseLoginRequest:
    """parse_login_request(body: bytes) → LoginRequest."""

    def test_valid_body(self) -> None:
        body = (
            b"TestUser\n"
            b"d41d8cd98f00b204e9800998ecf8427e\n"
            b"b20240101.1|9|1|abc123:def456:ghi789:jkl012:mno345|0\n"
        )
        result = parse_login_request(body)

        assert isinstance(result, LoginRequest)
        assert result.username == "TestUser"
        assert result.password_md5 == "d41d8cd98f00b204e9800998ecf8427e"
        assert isinstance(result.client_info, ClientInfo)

    def test_client_info_fields_parsed(self) -> None:
        body = b"Player\nhashvalue\nb20240101.1|9|1|hashes|0\n"
        result = parse_login_request(body)

        assert result.client_info.osu_version == "b20240101.1"
        assert result.client_info.utc_offset == 9
        assert result.client_info.display_city is True
        assert result.client_info.client_hashes == "hashes"
        assert result.client_info.pm_private is False

    def test_crlf_line_endings(self) -> None:
        body = b"User\r\npasshash\r\nb20240101|0|0|h|1\r\n"
        result = parse_login_request(body)

        assert result.username == "User"
        assert result.password_md5 == "passhash"
        assert result.client_info.osu_version == "b20240101"

    def test_no_trailing_newline(self) -> None:
        body = b"User\npasshash\nb20240101|0|0|h|1"
        result = parse_login_request(body)

        assert result.username == "User"
        assert result.password_md5 == "passhash"

    def test_empty_body_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="login request body"):
            _ = parse_login_request(b"")

    def test_one_line_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="login request body"):
            _ = parse_login_request(b"username_only\n")

    def test_two_lines_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="login request body"):
            _ = parse_login_request(b"user\npasshash\n")

    def test_whitespace_only_body_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="login request body"):
            _ = parse_login_request(b"  \n  \n")

    def test_username_preserved_as_is(self) -> None:
        """Username should not be normalized — that is the domain layer's job."""
        body = b"My User Name\nhash\nb20240101|0|0|h|0\n"
        result = parse_login_request(body)
        assert result.username == "My User Name"


class TestParseClientInfo:
    """parse_client_info(raw: str) → ClientInfo."""

    def test_valid_client_info(self) -> None:
        raw = "b20240101.1|9|1|abc123:def456:ghi789:jkl012:mno345|0"
        result = parse_client_info(raw)

        assert isinstance(result, ClientInfo)
        assert result.osu_version == "b20240101.1"
        assert result.utc_offset == 9
        assert result.display_city is True
        assert result.client_hashes == "abc123:def456:ghi789:jkl012:mno345"
        assert result.pm_private is False

    def test_negative_utc_offset(self) -> None:
        raw = "b20240101|-5|0|hashes|0"
        result = parse_client_info(raw)
        assert result.utc_offset == -5

    def test_zero_utc_offset(self) -> None:
        raw = "b20240101|0|0|hashes|0"
        result = parse_client_info(raw)
        assert result.utc_offset == 0

    def test_large_positive_utc_offset(self) -> None:
        """Tests parsing a large valid positive offset.
        The magic number '14' represents UTC+14, the maximum valid time zone offset.
        """
        raw = "b20240101|14|0|hashes|0"
        result = parse_client_info(raw)
        assert result.utc_offset == 14

    def test_large_negative_utc_offset(self) -> None:
        """Tests parsing a large valid negative offset.
        The magic number '-12' represents UTC-12, the minimum valid time zone offset.
        """
        raw = "b20240101|-12|0|hashes|0"
        result = parse_client_info(raw)
        assert result.utc_offset == -12

    def test_parse_valid_client_info(self) -> None:
        """Req 2.1: Parses standard pipelined client info string.
        The magic number '9' below represents a valid UTC+9 (JST) time zone offset.
        """
        raw = "b20240101|9|1|hashes|0"
        result = parse_client_info(raw)
        assert result.display_city is True

    def test_display_city_false(self) -> None:
        raw = "b20240101|0|0|hashes|0"
        result = parse_client_info(raw)
        assert result.display_city is False

    def test_pm_private_true(self) -> None:
        raw = "b20240101|0|0|hashes|1"
        result = parse_client_info(raw)
        assert result.pm_private is True

    def test_pm_private_false(self) -> None:
        raw = "b20240101|0|0|hashes|0"
        result = parse_client_info(raw)
        assert result.pm_private is False

    def test_insufficient_fields_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="client_info"):
            _ = parse_client_info("b20240101|9|1")

    def test_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="client_info"):
            _ = parse_client_info("")

    def test_four_fields_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="client_info"):
            _ = parse_client_info("b20240101|9|1|hashes")

    def test_non_integer_utc_offset_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="utc_offset"):
            _ = parse_client_info("b20240101|abc|1|hashes|0")

    def test_non_boolean_display_city_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="display_city"):
            _ = parse_client_info("b20240101|0|yes|hashes|0")

    def test_non_boolean_pm_private_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="pm_private"):
            _ = parse_client_info("b20240101|0|0|hashes|yes")

    def test_client_hashes_with_colons_preserved(self) -> None:
        """Client hashes are colon-separated and should be preserved as-is."""
        raw = "b20240101|0|0|a:b:c:d:e|0"
        result = parse_client_info(raw)
        assert result.client_hashes == "a:b:c:d:e"

    def test_extra_fields_ignored(self) -> None:
        """If the client sends extra pipe-delimited fields, ignore them gracefully."""
        raw = "b20240101|0|0|hashes|0|extra_field|another"
        result = parse_client_info(raw)
        assert result.osu_version == "b20240101"
        assert result.pm_private is False
