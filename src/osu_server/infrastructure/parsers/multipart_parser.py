"""Multipart form data parser for osu! score submissions."""

import base64
import binascii
from dataclasses import dataclass
from email import message_from_bytes
from email.message import Message

_REPLAY_FIELD_INDEX = 1
_RIJNDAEL_IV_SIZE = 32
_DEFAULT_TOTAL_BODY_SIZE = 1_048_576
_DEFAULT_REPLAY_SIZE = 1_048_576
_DEFAULT_TEXT_FIELD_SIZE = 65_536
_DEFAULT_SCORE_PAYLOAD_FIELD_SIZE = 262_144
_DEFAULT_OPAQUE_FIELD_SIZE = 262_144
_OPAQUE_METADATA_FIELDS = ("fs", "bmk", "sbk", "c1", "st", "i", "token")


class ParseError(Exception):
    """Raised when multipart parsing fails."""


@dataclass(frozen=True, slots=True)
class MultipartLimits:
    """Configured multipart size limits."""

    total_body_size: int = _DEFAULT_TOTAL_BODY_SIZE
    replay_size: int = _DEFAULT_REPLAY_SIZE
    text_field_size: int = _DEFAULT_TEXT_FIELD_SIZE
    score_payload_field_size: int = _DEFAULT_SCORE_PAYLOAD_FIELD_SIZE
    opaque_field_size: int = _DEFAULT_OPAQUE_FIELD_SIZE


@dataclass(frozen=True, slots=True)
class ParsedSubmission:
    """Parsed multipart submission data."""

    encrypted_payload: bytes
    iv: bytes
    replay_data: bytes | None
    score_field_count: int
    password_md5: str
    client_hash: str
    fail_time_ms: int | None
    osu_version: str
    submission_metadata: dict[str, str]


def _decode_base64_field(field_name: str, value: bytes) -> bytes:
    encoded = value.strip()
    if not encoded:
        raise ParseError(f"Empty base64 field: {field_name}")

    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ParseError(f"Invalid base64 field: {field_name}") from e


def _collect_fields(msg: Message) -> dict[str, list[bytes]]:
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

    return fields


def _enforce_size_limit(label: str, actual: int, limit: int) -> None:
    if actual > limit:
        raise ParseError(f"{label} size exceeds limit: {actual} > {limit}")


def _validate_field_sizes(fields: dict[str, list[bytes]], limits: MultipartLimits) -> None:
    for field_name, field_values in fields.items():
        for index, value in enumerate(field_values):
            if field_name == "score":
                if index == _REPLAY_FIELD_INDEX:
                    _enforce_size_limit("replay", len(value), limits.replay_size)
                elif index == 0:
                    _enforce_size_limit(
                        "field 'score'",
                        len(value),
                        limits.score_payload_field_size,
                    )
                else:
                    _enforce_size_limit("field 'score'", len(value), limits.text_field_size)
                continue

            if field_name in _OPAQUE_METADATA_FIELDS:
                _enforce_size_limit(
                    f"field {field_name!r}",
                    len(value),
                    limits.opaque_field_size,
                )
                continue

            _enforce_size_limit(f"field {field_name!r}", len(value), limits.text_field_size)


def _extract_optional_metadata(fields: dict[str, list[bytes]]) -> dict[str, str]:
    submission_metadata: dict[str, str] = {}
    for field_name in _OPAQUE_METADATA_FIELDS:
        field_values = fields.get(field_name)
        if field_values:
            try:
                submission_metadata[field_name] = field_values[0].decode("utf-8")
            except UnicodeDecodeError:
                submission_metadata[field_name] = field_values[0].hex()

    return submission_metadata


def _extract_required_fields(
    fields: dict[str, list[bytes]],
) -> tuple[bytes, bytes | None, int, bytes, str, str, int | None, str]:
    score_fields = fields.get("score", [])
    if len(score_fields) < 1:
        raise ParseError("Missing required field: score")

    encrypted_payload = _decode_base64_field("score", score_fields[0])
    replay_data = None
    if len(score_fields) > _REPLAY_FIELD_INDEX and score_fields[_REPLAY_FIELD_INDEX]:
        replay_data = score_fields[_REPLAY_FIELD_INDEX]
    score_field_count = len(score_fields)

    iv = _decode_base64_field("iv", fields["iv"][0])
    if len(iv) != _RIJNDAEL_IV_SIZE:
        msg = f"Invalid iv length: expected {_RIJNDAEL_IV_SIZE} bytes, got {len(iv)}"
        raise ParseError(msg)

    password_md5 = fields["pass"][0].decode("utf-8")
    client_hash = fields["x"][0].decode("utf-8")
    osu_version = fields["osuver"][0].decode("utf-8")

    fail_time_ms: int | None = None
    ft_values = fields.get("ft")
    if ft_values:
        ft_str = ft_values[0].decode("utf-8")
        if ft_str:
            fail_time_ms = int(ft_str)

    return (
        encrypted_payload,
        replay_data,
        score_field_count,
        iv,
        password_md5,
        client_hash,
        fail_time_ms,
        osu_version,
    )


def parse(
    body: bytes,
    content_type: str,
    limits: MultipartLimits | None = None,
) -> ParsedSubmission:
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
    effective_limits = limits or MultipartLimits()

    if not body:
        raise ParseError("Request body cannot be empty")
    _enforce_size_limit("request body", len(body), effective_limits.total_body_size)

    if not content_type or "multipart/form-data" not in content_type:
        raise ParseError("Content-Type must be multipart/form-data")

    # Parse multipart using email module
    headers = f"Content-Type: {content_type}\r\n\r\n".encode()
    msg = message_from_bytes(headers + body)

    if not msg.is_multipart():
        raise ParseError("Request is not multipart")

    fields = _collect_fields(msg)
    _validate_field_sizes(fields, effective_limits)

    # Extract required fields
    try:
        (
            encrypted_payload,
            replay_data,
            score_field_count,
            iv,
            password_md5,
            client_hash,
            fail_time_ms,
            osu_version,
        ) = _extract_required_fields(fields)

    except (KeyError, IndexError) as e:
        raise ParseError(f"Missing required field: {e}") from e
    except (ValueError, UnicodeDecodeError) as e:
        raise ParseError(f"Invalid field format: {e}") from e

    return ParsedSubmission(
        encrypted_payload=encrypted_payload,
        iv=iv,
        replay_data=replay_data,
        score_field_count=score_field_count,
        password_md5=password_md5,
        client_hash=client_hash,
        fail_time_ms=fail_time_ms,
        osu_version=osu_version,
        submission_metadata=_extract_optional_metadata(fields),
    )
