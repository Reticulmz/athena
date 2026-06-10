"""Score payload parser."""

from dataclasses import dataclass

_EXPECTED_FIELD_COUNT = 16


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


def parse(payload: str) -> ParsedScore:
    """Parse colon-separated score payload.

    Format: user_id:username:beatmap_checksum:online_checksum:ruleset:mods:
    n300:n100:n50:geki:katu:miss:score:max_combo:perfect:passed
    """
    if not payload:
        raise ParseError("Payload cannot be empty")

    fields = payload.split(":")
    if len(fields) != _EXPECTED_FIELD_COUNT:
        raise ParseError(f"Expected {_EXPECTED_FIELD_COUNT} fields, got {len(fields)}")

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
            perfect=fields[14] == "1",
            passed=fields[15] == "1",
        )
    except ValueError as e:
        raise ParseError(f"Failed to parse integer field: {e}") from e
