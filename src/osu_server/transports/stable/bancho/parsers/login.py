"""Stable Bancho login request body を domain login input へ解析する."""

from __future__ import annotations

from osu_server.domain.identity.authentication import ClientInfo, LoginRequest

_EXPECTED_LINE_COUNT = 3
_EXPECTED_FIELD_COUNT = 5

# Valid UTC offsets: -12 to +14 in practice, but we allow the full
# representable range after the +24 wire offset (uint8 0-255).
_UTC_OFFSET_MIN = -24
_UTC_OFFSET_MAX = 24


def parse_login_request(body: bytes) -> LoginRequest:
    """受け取った raw login request body を LoginRequest へ解析する.

    Args:
        body (bytes): HTTP request body から取得した raw bytes.

    Returns:
        LoginRequest: username, password MD5, ClientInfo を含む login request.

    Raises:
        UnicodeDecodeError: body を UTF-8 text として復号できない場合.
        ValueError: 必須行または client info field が不足するか空文字列の場合, または utc_offset
            か boolean field を解析できない場合.

    Notes:
        先頭の 3 行だけを username, password_md5, client_info として使う. 末尾の空行は無視する.
    """
    text = body.decode("utf-8")
    lines = [line.strip() for line in text.splitlines()]
    # Remove trailing empty lines (from trailing newline)
    while lines and not lines[-1]:
        _ = lines.pop()

    if len(lines) < _EXPECTED_LINE_COUNT:
        msg = (
            f"Invalid login request body: expected {_EXPECTED_LINE_COUNT} lines, got {len(lines)}"
        )
        raise ValueError(msg)

    username = lines[0]
    password_md5 = lines[1]
    client_info_raw = lines[2]

    if not username or not password_md5:
        msg = "Invalid login request body: username and password_md5 must not be empty"
        raise ValueError(msg)

    client_info = parse_client_info(client_info_raw)

    return LoginRequest(
        username=username,
        password_md5=password_md5,
        client_info=client_info,
    )


def parse_client_info(raw: str) -> ClientInfo:
    """client_info の pipe 区切り text を ClientInfo へ解析する.

    Args:
        raw (str): osu_version, utc_offset, display_city, client_hashes, pm_private を含む text.

    Returns:
        ClientInfo: 型変換済みの stable client metadata.

    Raises:
        ValueError: field が 5 個未満か utc_offset または boolean field を解析できない場合.

    Notes:
        5 個を超える field は無視する. utc_offset は stable wire の表現可能範囲へ clamp する.
    """
    parts = raw.split("|")

    if len(parts) < _EXPECTED_FIELD_COUNT:
        msg = (
            f"Invalid client_info: expected at least {_EXPECTED_FIELD_COUNT} "
            f"pipe-delimited fields, got {len(parts)}"
        )
        raise ValueError(msg)

    osu_version = parts[0]
    utc_offset = max(_UTC_OFFSET_MIN, min(_UTC_OFFSET_MAX, _parse_int(parts[1], "utc_offset")))
    display_city = _parse_bool(parts[2], "display_city")
    client_hashes = parts[3]
    pm_private = _parse_bool(parts[4], "pm_private")

    return ClientInfo(
        osu_version=osu_version,
        utc_offset=utc_offset,
        display_city=display_city,
        client_hashes=client_hashes,
        pm_private=pm_private,
    )


def _parse_int(value: str, field_name: str) -> int:
    """Protocol field text を整数へ変換し失敗時の field 名を保持する.

    Args:
        value (str): 整数として解釈する client field text.
        field_name (str): error message に含める protocol field 名.

    Returns:
        int: value を int として変換した値.

    Raises:
        ValueError: value が整数として解釈できない場合.
    """
    try:
        return int(value)
    except ValueError:
        msg = f"Invalid {field_name}: expected integer, got {value!r}"
        raise ValueError(msg) from None


def _parse_bool(value: str, field_name: str) -> bool:
    """0 または 1 の client field text を bool へ変換する.

    Args:
        value (str): boolean を表す 0 または 1 の text.
        field_name (str): error message に含める protocol field 名.

    Returns:
        bool: value が 1 なら True, 0 なら False.

    Raises:
        ValueError: value が 0 と 1 のどちらでもない場合.
    """
    if value == "1":
        return True
    if value == "0":
        return False
    msg = f"Invalid {field_name}: expected '0' or '1', got {value!r}"
    raise ValueError(msg)
