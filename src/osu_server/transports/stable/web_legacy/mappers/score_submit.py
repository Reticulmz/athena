"""Stable legacy score submit request and response mappers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.responses import Response

from osu_server.domain.compatibility.stable.mods import stable_mod_bitmask_to_mod_combination
from osu_server.domain.scores.payload_parser import ParsedScore, ParseError
from osu_server.infrastructure.parsers.multipart_parser import (
    MultipartLimits,
    parse,
)
from osu_server.infrastructure.parsers.multipart_parser import (
    ParseError as MultipartParseError,
)
from osu_server.services.commands.scores import (
    ParsedSubmissionInput,
    SubmissionOutcome,
    SubmissionResult,
)

if TYPE_CHECKING:
    from datetime import datetime

_LEGACY_FIELD_COUNT = 16
_STABLE_MIN_FIELD_COUNT = 16
_STABLE_MAX_FIELD_COUNT = 19
_NO_PAYLOAD_USER_ID = 0
_STABLE_SUBMITTED_AT_INDEX = 16
_STABLE_CLIENT_VERSION_INDEX = 17
_STABLE_CLIENT_CHECKSUM_INDEX = 18


class StableScorePayloadParser:
    """Map stable score payload text into canonical score domain values."""

    def parse(self, payload: str) -> ParsedScore:
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


@dataclass(frozen=True, slots=True)
class StableScoreSubmitCommandMapping:
    """Mapped command input plus stable transport diagnostics."""

    input_data: ParsedSubmissionInput
    score_field_count: int
    replay_present: bool
    replay_byte_size: int | None
    fail_time_ms: int | None
    osu_version: str | None


class StableScoreSubmitMapper:
    """Map stable legacy score submit wire data to command inputs and responses."""

    def __init__(self, limits: MultipartLimits | None = None) -> None:
        self._limits: MultipartLimits = limits or MultipartLimits()

    def to_command_input(
        self,
        *,
        body: bytes,
        content_type: str,
        submitted_at: datetime,
    ) -> ParsedSubmissionInput:
        return self.to_command_mapping(
            body=body,
            content_type=content_type,
            submitted_at=submitted_at,
        ).input_data

    def to_command_mapping(
        self,
        *,
        body: bytes,
        content_type: str,
        submitted_at: datetime,
    ) -> StableScoreSubmitCommandMapping:
        parsed = parse(body, content_type, self._limits)
        input_data = ParsedSubmissionInput(
            encrypted_payload=parsed.encrypted_payload,
            iv=parsed.iv,
            replay_data=parsed.replay_data,
            password_md5=parsed.password_md5,
            client_hash=parsed.client_hash,
            fail_time_ms=parsed.fail_time_ms,
            osu_version=parsed.osu_version,
            submitted_at=submitted_at,
            submission_metadata=parsed.submission_metadata,
        )
        return StableScoreSubmitCommandMapping(
            input_data=input_data,
            score_field_count=parsed.score_field_count,
            replay_present=parsed.replay_data is not None,
            replay_byte_size=len(parsed.replay_data) if parsed.replay_data is not None else None,
            fail_time_ms=parsed.fail_time_ms,
            osu_version=parsed.osu_version,
        )

    def to_response(self, result: SubmissionResult) -> Response:
        if result.outcome == SubmissionOutcome.COMPLETED:
            return _format_completed_response(
                beatmap_id=result.beatmap_id or 0,
                beatmap_set_id=result.beatmapset_id or 0,
                stable_pp=result.stable_pp,
            )
        if result.outcome in {SubmissionOutcome.RETRYABLE, SubmissionOutcome.ACCEPTED_PENDING}:
            return Response(b"error: yes", status_code=200)
        return Response(b"error: no", status_code=200)


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
            mods=stable_mod_bitmask_to_mod_combination(int(fields[5])),
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
            mods=stable_mod_bitmask_to_mod_combination(int(fields[13])),
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


def _format_completed_response(
    *,
    beatmap_id: int,
    beatmap_set_id: int,
    stable_pp: int | None,
) -> Response:
    beatmap_playcount = 1
    pp = stable_pp or 0

    body = f"{beatmap_id}:{beatmap_set_id}:{beatmap_playcount}:3\n".encode()
    body += b"chartId:overall\n"
    body += b"chartUrl:\n"
    body += b"chartName:Overall Ranking\n"
    body += b"achieved:0\n"
    body += b"rank:0\n"
    body += b"rankBefore:0\n"
    body += b"rankedScoreBefore:0\n"
    body += b"rankedScore:0\n"
    body += b"totalScore:0\n"
    body += b"maxCombo:0\n"
    body += b"accuracy:0\n"
    body += f"pp:{pp}\n".encode()

    return Response(body, status_code=200)


__all__ = [
    "MultipartParseError",
    "StableScorePayloadParser",
    "StableScoreSubmitCommandMapping",
    "StableScoreSubmitMapper",
]
