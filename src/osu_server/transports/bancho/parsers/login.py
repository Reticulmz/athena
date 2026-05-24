"""Login request parser for the osu! stable bancho protocol.

Parses the raw HTTP body of a login request into structured domain objects.
The osu! stable client sends login data as three newline-separated lines:
  username\\npassword_md5\\nclient_info_line\\n

The client_info line is pipe-delimited:
  osu_version|utc_offset|display_city|client_hashes|pm_private
"""

from __future__ import annotations

from osu_server.domain.auth import ClientInfo, LoginRequest

_EXPECTED_LINE_COUNT = 3
_EXPECTED_FIELD_COUNT = 5

# Valid UTC offsets: -12 to +14 in practice, but we allow the full
# representable range after the +24 wire offset (uint8 0-255).
_UTC_OFFSET_MIN = -24
_UTC_OFFSET_MAX = 24


def parse_login_request(body: bytes) -> LoginRequest:
    """Parse a raw login request body into a ``LoginRequest``.

    Args:
        body: Raw bytes from the HTTP request body.

    Returns:
        A populated ``LoginRequest`` with parsed ``ClientInfo``.

    Raises:
        ValueError: If the body does not contain exactly 3 non-empty lines.
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
    """Parse a pipe-delimited client_info string into a ``ClientInfo``.

    Expected format: ``osu_version|utc_offset|display_city|client_hashes|pm_private``

    Args:
        raw: The pipe-delimited client_info string.

    Returns:
        A populated ``ClientInfo``.

    Raises:
        ValueError: If there are fewer than 5 fields or type conversion fails.
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
    """Convert a string to int with a descriptive error on failure."""
    try:
        return int(value)
    except ValueError:
        msg = f"Invalid {field_name}: expected integer, got {value!r}"
        raise ValueError(msg) from None


def _parse_bool(value: str, field_name: str) -> bool:
    """Convert '1'/'0' to bool with a descriptive error on failure."""
    if value == "1":
        return True
    if value == "0":
        return False
    msg = f"Invalid {field_name}: expected '0' or '1', got {value!r}"
    raise ValueError(msg)
