"""Unit tests for multipart parser."""

import pytest

from osu_server.infrastructure.parsers.multipart_parser import ParseError, parse


def make_multipart_body(boundary: str, fields: list[tuple[str, bytes]]) -> bytes:
    """Build multipart body from field list."""
    parts: list[bytes] = []
    for name, value in fields:
        part = (
            (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n').encode()
            + value
            + b"\r\n"
        )
        parts.append(part)
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


def test_parse_valid_multipart_with_all_required_fields():
    """Valid multipart with all required fields should parse successfully."""
    boundary = "----boundary"
    fields = [
        ("score", b"encrypted_payload_data"),
        ("iv", b"iv_bytes_here"),
        ("pass", b"password_md5_hash"),
        ("x", b"client_hash_value"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse(body, content_type)

    assert result.encrypted_payload == b"encrypted_payload_data"
    assert result.iv == b"iv_bytes_here"
    assert result.password_md5 == "password_md5_hash"
    assert result.client_hash == "client_hash_value"
    assert result.osu_version == "20260412"
    assert result.replay_data is None
    assert result.fail_time_ms is None
    assert result.submission_metadata == {}


def test_parse_duplicate_score_field_order_preservation():
    """First score field is payload, second is replay."""
    boundary = "----boundary"
    fields = [
        ("score", b"encrypted_payload"),
        ("score", b"replay_binary_data"),
        ("iv", b"iv_bytes"),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse(body, content_type)

    assert result.encrypted_payload == b"encrypted_payload"
    assert result.replay_data == b"replay_binary_data"


def test_parse_with_optional_fields():
    """Optional fields should be preserved in submission_metadata."""
    boundary = "----boundary"
    fields = [
        ("score", b"encrypted_payload"),
        ("iv", b"iv_bytes"),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
        ("fs", b"fullscreen_flag"),
        ("bmk", b"beatmap_key"),
        ("sbk", b"score_key"),
        ("c1", b"custom1"),
        ("st", b"score_time"),
        ("i", b"info_field"),
        ("token", b"session_token"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse(body, content_type)

    assert result.submission_metadata["fs"] == "fullscreen_flag"
    assert result.submission_metadata["bmk"] == "beatmap_key"
    assert result.submission_metadata["sbk"] == "score_key"
    assert result.submission_metadata["c1"] == "custom1"
    assert result.submission_metadata["st"] == "score_time"
    assert result.submission_metadata["i"] == "info_field"
    assert result.submission_metadata["token"] == "session_token"


def test_parse_with_fail_time():
    """ft field should be parsed as fail_time_ms."""
    boundary = "----boundary"
    fields = [
        ("score", b"encrypted_payload"),
        ("iv", b"iv_bytes"),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
        ("ft", b"12345"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse(body, content_type)

    assert result.fail_time_ms == 12345


def test_parse_missing_required_field_score():
    """Missing score field should raise ParseError."""
    boundary = "----boundary"
    fields = [
        ("iv", b"iv_bytes"),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    with pytest.raises(ParseError, match="Missing required field: score"):
        _ = parse(body, content_type)


def test_parse_missing_required_field_iv():
    """Missing iv field should raise ParseError."""
    boundary = "----boundary"
    fields = [
        ("score", b"encrypted_payload"),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    with pytest.raises(ParseError, match="Missing required field"):
        _ = parse(body, content_type)


def test_parse_empty_body():
    """Empty body should raise ParseError."""
    with pytest.raises(ParseError, match="Request body cannot be empty"):
        _ = parse(b"", "multipart/form-data; boundary=----boundary")


def test_parse_invalid_content_type():
    """Invalid Content-Type should raise ParseError."""
    with pytest.raises(ParseError, match="Content-Type must be multipart/form-data"):
        _ = parse(b"some data", "application/json")


def test_parse_non_multipart_body():
    """Non-multipart body should raise ParseError."""
    body = b"not a multipart body"
    content_type = "multipart/form-data; boundary=----boundary"

    with pytest.raises(ParseError, match="Request is not multipart"):
        _ = parse(body, content_type)
