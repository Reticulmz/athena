"""stable score submissionのmultipart parser境界を検証するmodule."""

import base64

import pytest

from osu_server.infrastructure.parsers.multipart_parser import MultipartLimits, ParseError, parse

RAW_SCORE = b"encrypted_payload_data"
RAW_IV = b"0" * 32
SCORE_B64 = base64.b64encode(RAW_SCORE)
IV_B64 = base64.b64encode(RAW_IV)


def make_multipart_body(boundary: str, fields: list[tuple[str, bytes]]) -> bytes:
    """指定fieldを含むmultipart request bodyを構築する.

    Args:
        boundary (str): multipart bodyを区切るboundary文字列.
        fields (list[tuple[str, bytes]]): field名とraw valueの順序付き組.

    Returns:
        bytes: 終端boundaryを含むmultipart request body.
    """
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
    """必須fieldをすべて含むmultipart bodyがsubmission値へparseされることを検証する.

    Returns:
        None: decoded payloadと必須fieldおよび既定optional valueを検証して完了する.
    """
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


def test_parse_normalizes_uppercase_password_md5_hex():
    """大文字のstable password MD5 hexが小文字へcanonicalizeされることを検証する.

    Returns:
        None: canonicalized password MD5値を検証して完了する.
    """
    boundary = "----boundary"
    fields = [
        ("score", SCORE_B64),
        ("iv", IV_B64),
        ("pass", b"ABCDEF0123456789ABCDEF0123456789"),
        ("x", b"client_hash_value"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse(body, content_type)

    assert result.password_md5 == "abcdef0123456789abcdef0123456789"


def test_parse_preserves_non_md5_password_credential():
    """32文字hexでないpassword credentialが変更されず保持されることを検証する.

    Returns:
        None: non-MD5 credentialの保存値を検証して完了する.
    """
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

    assert result.password_md5 == "password_md5_hash"


def test_parse_duplicate_score_field_order_preservation():
    """重複score fieldの先頭をpayload, 後続をreplayとして保持することを検証する.

    Returns:
        None: encrypted payloadとreplayの順序を検証して完了する.
    """
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


def test_parse_empty_replay_score_field_as_absent_replay():
    """空の2番目score fieldがreplay未提出として扱われることを検証する.

    Returns:
        None: payload維持とNone replayを検証して完了する.
    """
    boundary = "----boundary"
    encrypted_payload = b"encrypted_payload"
    fields = [
        ("score", base64.b64encode(encrypted_payload)),
        ("score", b""),
        ("iv", IV_B64),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse(body, content_type)

    assert result.encrypted_payload == encrypted_payload
    assert result.replay_data is None
    assert result.score_field_count == 2


def test_parse_with_optional_fields():
    """任意fieldがsubmission metadataへ名前と値を維持して保存されることを検証する.

    Returns:
        None: すべてのoptional metadata fieldを検証して完了する.
    """
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
    """Ft fieldがintegerのfail_time_msとしてparseされることを検証する.

    Returns:
        None: millisecond値への変換結果を検証して完了する.
    """
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


def test_parse_malformed_fail_time_as_unavailable():
    """不正なft fieldでも他の有効submissionを拒否せずNoneにすることを検証する.

    Returns:
        None: unavailable fail_time_msを検証して完了する.
    """
    boundary = "----boundary"
    fields = [
        ("score", SCORE_B64),
        ("iv", IV_B64),
        ("pass", b"pass_hash"),
        ("x", b"client_hash"),
        ("osuver", b"20260412"),
        ("ft", b"not-an-int"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse(body, content_type)

    assert result.fail_time_ms is None


def test_parse_keeps_stable_x_as_client_hash_only():
    """Stable x fieldをclient_hashだけとして保持し未確認分類へ使わないことを検証する.

    Returns:
        None: client hashとNone exit classificationを検証して完了する.
    """
    boundary = "----boundary"
    fields = [
        ("score", SCORE_B64),
        ("iv", IV_B64),
        ("pass", b"pass_hash"),
        ("x", b"1"),
        ("osuver", b"20260412"),
    ]
    body = make_multipart_body(boundary, fields)
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse(body, content_type)

    assert result.client_hash == "1"
    assert result.submit_exit_classification is None


def test_parse_missing_required_field_score():
    """必須score fieldがないmultipart bodyでParseErrorを送出することを検証する.

    Returns:
        None: missing score validation例外を検証して完了する.
    """
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
    """必須iv fieldがないmultipart bodyでParseErrorを送出することを検証する.

    Returns:
        None: missing IV validation例外を検証して完了する.
    """
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
    """空request bodyでParseErrorを送出することを検証する.

    Returns:
        None: empty body validation例外を検証して完了する.
    """
    with pytest.raises(ParseError, match="Request body cannot be empty"):
        _ = parse(b"", "multipart/form-data; boundary=----boundary")


def test_parse_invalid_content_type():
    """multipartでないContent-TypeでParseErrorを送出することを検証する.

    Returns:
        None: Content-Type validation例外を検証して完了する.
    """
    with pytest.raises(ParseError, match="Content-Type must be multipart/form-data"):
        _ = parse(b"some data", "application/json")


def test_parse_rejects_body_over_configured_limit():
    """設定したtotal body sizeを超えるrequestがparse前に拒否されることを検証する.

    Returns:
        None: request body size validation例外を検証して完了する.
    """
    body = b"x" * 64
    limits = MultipartLimits(total_body_size=16, replay_size=64, text_field_size=64)

    with pytest.raises(ParseError, match="request body size exceeds limit"):
        _ = parse(body, "multipart/form-data; boundary=----boundary", limits)


def test_parse_rejects_replay_over_configured_limit():
    """設定したreplay sizeを超える2番目score fieldが拒否されることを検証する.

    Returns:
        None: replay size validation例外を検証して完了する.
    """
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
    """設定したtext field sizeを超えるcredential fieldが拒否されることを検証する.

    Returns:
        None: text field size validation例外を検証して完了する.
    """
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
    """Opaque tokenがtext上限を超えてもopaque上限内なら受理されることを検証する.

    Returns:
        None: token metadataの保存値を検証して完了する.
    """
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
    """Opaque tokenが設定したopaque field上限を超えると拒否されることを検証する.

    Returns:
        None: opaque field size validation例外を検証して完了する.
    """
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
    """設定したscore payload field上限を超える先頭score fieldが拒否されることを検証する.

    Returns:
        None: score payload size validation例外を検証して完了する.
    """
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
    """multipart形式でないbodyをparseするとParseErrorになることを検証する.

    Returns:
        None: multipart structure validation例外を検証して完了する.
    """
    body = b"not a multipart body"
    content_type = "multipart/form-data; boundary=----boundary"

    with pytest.raises(ParseError, match="Request is not multipart"):
        _ = parse(body, content_type)


def test_parse_invalid_base64_score():
    """不正なBase64 score fieldをparseするとParseErrorになることを検証する.

    Returns:
        None: score Base64 validation例外を検証して完了する.
    """
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
    """Rijndael-256 block sizeでないdecoded IVをParseErrorとして拒否することを検証する.

    Returns:
        None: IV length validation例外を検証して完了する.
    """
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
