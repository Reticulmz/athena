"""Score payload parser."""

from dataclasses import dataclass

_LEGACY_FIELD_COUNT = 16
_STABLE_MIN_FIELD_COUNT = 16
_STABLE_MAX_FIELD_COUNT = 19
_NO_PAYLOAD_USER_ID = 0
_STABLE_SUBMITTED_AT_INDEX = 16
_STABLE_CLIENT_VERSION_INDEX = 17
_STABLE_CLIENT_CHECKSUM_INDEX = 18


class ParseError(Exception):
    """Raised when payload parsing fails."""


@dataclass(frozen=True, slots=True)
class ParsedScore:
    """Parsed score data from colon-separated payload."""

    user_id: int
    username: str
    beatmap_checksum: str
    online_checksum: str
    ruleset: int
    mods: int
    n300: int
    n100: int
    n50: int
    geki: int
    katu: int
    miss: int
    score: int
    max_combo: int
    perfect: bool
    passed: bool
    client_grade: str | None = None
    client_submitted_at: str | None = None
    client_version: str | None = None
    client_checksum: str | None = None


def parse(payload: str) -> ParsedScore:
    """Parse colon-separated score payload.

    Supported formats:
    - Legacy tests: user_id:username:beatmap_checksum:online_checksum:ruleset:mods:
      n300:n100:n50:geki:katu:miss:score:max_combo:perfect:passed
    - Stable client: beatmap_checksum:username:online_checksum:n300:n100:n50:
      geki:katu:miss:score:max_combo:perfect:grade:mods:passed:ruleset:
      submitted_at:client_version:client_checksum
    """
    if not payload:
        raise ParseError("Payload cannot be empty")

    fields = payload.split(":")

    if len(fields) == _LEGACY_FIELD_COUNT and _is_int(fields[0]):
        return _parse_legacy_payload(fields)

    if _STABLE_MIN_FIELD_COUNT <= len(fields) <= _STABLE_MAX_FIELD_COUNT:
        return _parse_stable_payload(fields)

    raise ParseError(
        f"Expected 16 legacy fields or 16-19 stable fields, got {len(fields)}",
    )


def _is_int(value: str) -> bool:
    try:
        _ = int(value)
    except ValueError:
        return False
    return True


def _parse_bool(value: str) -> bool:
    match value:
        case "1" | "True" | "true":
            return True
        case "0" | "False" | "false":
            return False
        case _:
            raise ValueError(f"invalid boolean value: {value}")


def _parse_legacy_payload(fields: list[str]) -> ParsedScore:
    try:
        return ParsedScore(
            user_id=int(fields[0]),
            username=fields[1],
            beatmap_checksum=fields[2],
            online_checksum=fields[3],
            ruleset=int(fields[4]),
            mods=int(fields[5]),
            n300=int(fields[6]),
            n100=int(fields[7]),
            n50=int(fields[8]),
            geki=int(fields[9]),
            katu=int(fields[10]),
            miss=int(fields[11]),
            score=int(fields[12]),
            max_combo=int(fields[13]),
            perfect=_parse_bool(fields[14]),
            passed=_parse_bool(fields[15]),
        )
    except ValueError as e:
        raise ParseError(f"Failed to parse integer field: {e}") from e


def _parse_stable_payload(fields: list[str]) -> ParsedScore:
    try:
        return ParsedScore(
            user_id=_NO_PAYLOAD_USER_ID,
            username=fields[1],
            beatmap_checksum=fields[0],
            online_checksum=fields[2],
            n300=int(fields[3]),
            n100=int(fields[4]),
            n50=int(fields[5]),
            geki=int(fields[6]),
            katu=int(fields[7]),
            miss=int(fields[8]),
            score=int(fields[9]),
            max_combo=int(fields[10]),
            perfect=_parse_bool(fields[11]),
            client_grade=fields[12],
            mods=int(fields[13]),
            passed=_parse_bool(fields[14]),
            ruleset=int(fields[15]),
            client_submitted_at=fields[_STABLE_SUBMITTED_AT_INDEX]
            if len(fields) > _STABLE_SUBMITTED_AT_INDEX
            else None,
            client_version=fields[_STABLE_CLIENT_VERSION_INDEX]
            if len(fields) > _STABLE_CLIENT_VERSION_INDEX
            else None,
            client_checksum=fields[_STABLE_CLIENT_CHECKSUM_INDEX]
            if len(fields) > _STABLE_CLIENT_CHECKSUM_INDEX
            else None,
        )
    except ValueError as e:
        raise ParseError(f"Failed to parse integer field: {e}") from e
