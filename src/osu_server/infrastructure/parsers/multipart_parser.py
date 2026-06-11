"""Multipart form data parser for osu! score submissions."""

from dataclasses import dataclass
from email import message_from_bytes

_REPLAY_FIELD_INDEX = 1


class ParseError(Exception):
    """Raised when multipart parsing fails."""


@dataclass(frozen=True, slots=True)
class ParsedSubmission:
    """Parsed multipart submission data."""

    encrypted_payload: bytes
    iv: bytes
    replay_data: bytes | None
    password_md5: str
    client_hash: str
    fail_time_ms: int | None
    osu_version: str
    submission_metadata: dict[str, str]


def parse(body: bytes, content_type: str) -> ParsedSubmission:  # noqa: PLR0912
    """Parse multipart form data from score submission.

    Args:
        body: Raw request body
        content_type: Content-Type header value

    Returns:
        ParsedSubmission with required and optional fields

    Raises:
        ParseError: If parsing fails or required fields are missing

    Note:
        Duplicate 'score' fields are handled specially:
        - First occurrence: encrypted score payload
        - Second occurrence: replay binary data
    """
    if not body:
        raise ParseError("Request body cannot be empty")

    if not content_type or "multipart/form-data" not in content_type:
        raise ParseError("Content-Type must be multipart/form-data")

    # Parse multipart using email module
    headers = f"Content-Type: {content_type}\r\n\r\n".encode()
    msg = message_from_bytes(headers + body)

    if not msg.is_multipart():
        raise ParseError("Request is not multipart")

    # Extract fields, preserving duplicate 'score' field order
    fields: dict[str, list[bytes]] = {}
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue

        name = part.get_param("name", header="content-disposition")
        if not name or not isinstance(name, str):
            continue

        payload = part.get_payload(decode=True)
        if payload is None or not isinstance(payload, bytes):
            continue

        if name not in fields:
            fields[name] = []
        fields[name].append(payload)

    # Extract required fields
    try:
        score_fields = fields.get("score", [])
        if len(score_fields) < 1:
            raise ParseError("Missing required field: score")

        encrypted_payload = score_fields[0]
        replay_data = (
            score_fields[_REPLAY_FIELD_INDEX] if len(score_fields) > _REPLAY_FIELD_INDEX else None
        )

        iv = fields["iv"][0]
        password_md5 = fields["pass"][0].decode("utf-8")
        client_hash = fields["x"][0].decode("utf-8")
        osu_version = fields["osuver"][0].decode("utf-8")

        # fail_time is optional (ft field)
        fail_time_ms: int | None = None
        ft_values = fields.get("ft")
        if ft_values:
            ft_str = ft_values[0].decode("utf-8")
            if ft_str:
                fail_time_ms = int(ft_str)

    except (KeyError, IndexError) as e:
        raise ParseError(f"Missing required field: {e}") from e
    except (ValueError, UnicodeDecodeError) as e:
        raise ParseError(f"Invalid field format: {e}") from e

    # Preserve optional fields for diagnostics
    submission_metadata: dict[str, str] = {}
    optional_fields = ["fs", "bmk", "sbk", "c1", "st", "i", "token"]
    for field_name in optional_fields:
        field_values = fields.get(field_name)
        if field_values:
            try:
                submission_metadata[field_name] = field_values[0].decode("utf-8")
            except UnicodeDecodeError:
                # Binary fields stored as hex
                submission_metadata[field_name] = field_values[0].hex()

    return ParsedSubmission(
        encrypted_payload=encrypted_payload,
        iv=iv,
        replay_data=replay_data,
        password_md5=password_md5,
        client_hash=client_hash,
        fail_time_ms=fail_time_ms,
        osu_version=osu_version,
        submission_metadata=submission_metadata,
    )
