"""Unit tests for multipart parser."""

import base64

import pytest

from osu_server.infrastructure.parsers.multipart_parser import MultipartLimits, ParseError, parse

RAW_SCORE = b"encrypted_payload_data"
RAW_IV = b"0" * 32
SCORE_B64 = base64.b64encode(RAW_SCORE)
IV_B64 = base64.b64encode(RAW_IV)


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
        ("score", SCORE_B64),
        ("iv", IV_B64),
        ("pass", b"password_md5_hash"),
        ("x", b"client_hash_value"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse(body, content_type)

    assert result.encrypted_payload == RAW_SCORE
    assert result.iv == RAW_IV
    assert result.password_md5 == "password_md5_hash"
    assert result.client_hash == "client_hash_value"
    assert result.osu_version == "20260412"
    assert result.replay_data is None
    assert result.score_field_count == 1
    assert result.fail_time_ms is None
    assert result.submission_metadata == {}


def test_parse_duplicate_score_field_order_preservation():
    """First score field is payload, second is replay."""
    boundary = "----boundary"
    encrypted_payload = b"encrypted_payload"
    fields = [
        ("score", base64.b64encode(encrypted_payload)),
        ("score", b"replay_binary_data"),
        ("iv", IV_B64),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse(body, content_type)

    assert result.encrypted_payload == encrypted_payload
    assert result.replay_data == b"replay_binary_data"
    assert result.score_field_count == 2


def test_parse_with_optional_fields():
    """Optional fields should be preserved in submission_metadata."""
    boundary = "----boundary"
    fields = [
        ("score", SCORE_B64),
        ("iv", IV_B64),
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
        ("score", SCORE_B64),
        ("iv", IV_B64),
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
        ("iv", IV_B64),
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
        ("score", SCORE_B64),
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


def test_parse_rejects_body_over_configured_limit():
    """Body size limit should reject oversized requests before parsing."""
    body = b"x" * 64
    limits = MultipartLimits(total_body_size=16, replay_size=64, text_field_size=64)

    with pytest.raises(ParseError, match="request body size exceeds limit"):
        _ = parse(body, "multipart/form-data; boundary=----boundary", limits)


def test_parse_rejects_replay_over_configured_limit():
    """Replay size limit should reject the second score field."""
    boundary = "----boundary"
    fields = [
        ("score", SCORE_B64),
        ("score", b"replay_binary_data"),
        ("iv", IV_B64),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"
    limits = MultipartLimits(total_body_size=1024, replay_size=4, text_field_size=128)

    with pytest.raises(ParseError, match="replay size exceeds limit"):
        _ = parse(body, content_type, limits)


def test_parse_rejects_text_field_over_configured_limit():
    """Text field size limit should reject credential and metadata fields."""
    boundary = "----boundary"
    fields = [
        ("score", SCORE_B64),
        ("pass", b"p" * 80),
        ("iv", IV_B64),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"
    limits = MultipartLimits(total_body_size=1024, replay_size=1024, text_field_size=64)

    with pytest.raises(ParseError, match="field 'pass' size exceeds limit"):
        _ = parse(body, content_type, limits)


def test_parse_allows_token_over_configured_text_limit_when_under_opaque_limit():
    """Opaque token field should not use the strict text field limit."""
    boundary = "----boundary"
    fields = [
        ("score", SCORE_B64),
        ("iv", IV_B64),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
        ("token", b"t" * 131_898),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"
    limits = MultipartLimits(
        total_body_size=262_144,
        replay_size=1024,
        text_field_size=64,
        opaque_field_size=262_144,
    )

    result = parse(body, content_type, limits)

    assert result.submission_metadata["token"] == "t" * 131_898


def test_parse_rejects_token_over_configured_opaque_limit():
    """Opaque token field size limit should still reject oversized values."""
    boundary = "----boundary"
    fields = [
        ("score", SCORE_B64),
        ("iv", IV_B64),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
        ("token", b"t" * 80),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"
    limits = MultipartLimits(
        total_body_size=1024,
        replay_size=1024,
        text_field_size=64,
        opaque_field_size=32,
    )

    with pytest.raises(ParseError, match="field 'token' size exceeds limit"):
        _ = parse(body, content_type, limits)


def test_parse_rejects_encrypted_score_payload_over_configured_score_payload_limit():
    """Score payload field size limit should reject the first score field."""
    boundary = "----boundary"
    fields = [
        ("score", SCORE_B64),
        ("iv", IV_B64),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"
    limits = MultipartLimits(
        total_body_size=1024,
        replay_size=1024,
        text_field_size=64,
        score_payload_field_size=4,
    )

    with pytest.raises(ParseError, match="field 'score' size exceeds limit"):
        _ = parse(body, content_type, limits)


def test_parse_non_multipart_body():
    """Non-multipart body should raise ParseError."""
    body = b"not a multipart body"
    content_type = "multipart/form-data; boundary=----boundary"

    with pytest.raises(ParseError, match="Request is not multipart"):
        _ = parse(body, content_type)


def test_parse_invalid_base64_score():
    """Invalid encoded score should raise ParseError."""
    boundary = "----boundary"
    fields = [
        ("score", b"not valid base64!"),
        ("iv", IV_B64),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    with pytest.raises(ParseError, match="Invalid base64 field: score"):
        _ = parse(body, content_type)


def test_parse_invalid_iv_length():
    """Decoded IV must match Rijndael-256 block size."""
    boundary = "----boundary"
    fields = [
        ("score", SCORE_B64),
        ("iv", base64.b64encode(b"short")),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    with pytest.raises(ParseError, match="Invalid iv length"):
        _ = parse(body, content_type)
