from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping


_SCORE_SUBMIT_COMPLETED_LINE_COUNT = 3
_GETSCORES_MIN_HEADER_LINES = 4
_GETSCORES_MIN_HEADER_FIELDS = 5
_GETSCORES_PERSONAL_BEST_LINE_INDEX = 4
_GETSCORES_SCORE_ROW_FIELD_COUNT = 16
_GETSCORES_SCORE_ROW_NUMERIC_FIELD_INDICES = (0, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14)
_GETSCORES_SCORE_ROW_BOOLEAN_FIELD_INDICES = (10, 15)


class GetscoresResponseKind(StrEnum):
    NOT_SUBMITTED = "not_submitted"
    UPDATE_AVAILABLE = "update_available"
    HEADER = "header"


@dataclass(frozen=True, slots=True)
class ScoreSubmitBeatmapMetadata:
    beatmap_id: int
    beatmapset_id: int
    beatmap_playcount: int
    beatmap_passcount: int
    approved_date: str


@dataclass(frozen=True, slots=True)
class ScoreSubmitChart:
    chart_id: str
    chart_url: str
    chart_name: str
    fields: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ScoreSubmitResponse:
    beatmap_metadata: ScoreSubmitBeatmapMetadata
    beatmap_chart: ScoreSubmitChart
    overall_chart: ScoreSubmitChart

    @property
    def achievement_notification(self) -> str | None:
        return self.overall_chart.fields.get("achievements-new")


@dataclass(frozen=True, slots=True)
class ScoreSubmitResponseParseResult:
    response: ScoreSubmitResponse | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class GetscoresHeader:
    status: int
    failed: bool
    beatmap_id: int
    beatmapset_id: int
    score_count: int
    offset: int
    display_line: str
    rating: int
    personal_best_row: str | None
    score_rows: tuple[str, ...]

    @property
    def empty_leaderboard(self) -> bool:
        return self.score_count == 0 and not self.score_rows


@dataclass(frozen=True, slots=True)
class GetscoresResponse:
    kind: GetscoresResponseKind
    header: GetscoresHeader | None = None


@dataclass(frozen=True, slots=True)
class GetscoresResponseParseResult:
    response: GetscoresResponse | None = None
    error: str | None = None


def parse_score_submit_response(body: bytes) -> ScoreSubmitResponseParseResult:
    text_result = _decode_body(body)
    if isinstance(text_result, _ParseError):
        return ScoreSubmitResponseParseResult(error=text_result.message)

    lines = text_result.splitlines()
    if len(lines) != _SCORE_SUBMIT_COMPLETED_LINE_COUNT:
        return ScoreSubmitResponseParseResult(error="expected completed score submit response")

    return _parse_score_submit_lines(lines)


def _parse_score_submit_lines(lines: list[str]) -> ScoreSubmitResponseParseResult:
    metadata_fields = _parse_key_value_line(lines[0])
    if isinstance(metadata_fields, _ParseError):
        return ScoreSubmitResponseParseResult(error=metadata_fields.message)

    beatmap_chart_result = _parse_chart_line(lines[1])
    if isinstance(beatmap_chart_result, _ParseError):
        return ScoreSubmitResponseParseResult(error=beatmap_chart_result.message)

    overall_chart_result = _parse_chart_line(lines[2])
    if isinstance(overall_chart_result, _ParseError):
        return ScoreSubmitResponseParseResult(error=overall_chart_result.message)

    metadata = _parse_score_submit_metadata(metadata_fields)
    if isinstance(metadata, _ParseError):
        return ScoreSubmitResponseParseResult(error=metadata.message)

    return ScoreSubmitResponseParseResult(
        response=ScoreSubmitResponse(
            beatmap_metadata=metadata,
            beatmap_chart=beatmap_chart_result,
            overall_chart=overall_chart_result,
        )
    )


def parse_getscores_response(body: bytes) -> GetscoresResponseParseResult:
    """Getscores response bodyをwire grammarまで検証して構造化する。

    Args:
        body (bytes): Stable getscores endpointから受け取ったresponse body。

    Returns:
        GetscoresResponseParseResult: Short responseまたはheader / score rowを検証した結果。

    Raises:
        None: Decodeまたはwire grammarの不正はresult.errorへ変換する。

    Notes:
        Headerのscore_countはPersonal Bestを含めず、leaderboard row数と一致する必要がある。
    """

    text_result = _decode_body(body)
    if isinstance(text_result, _ParseError):
        return GetscoresResponseParseResult(error=text_result.message)

    normalized = text_result.rstrip("\r\n")
    if normalized == "-1|false":
        return GetscoresResponseParseResult(
            response=GetscoresResponse(kind=GetscoresResponseKind.NOT_SUBMITTED)
        )
    if normalized == "1|false":
        return GetscoresResponseParseResult(
            response=GetscoresResponse(kind=GetscoresResponseKind.UPDATE_AVAILABLE)
        )

    lines = text_result.splitlines()
    if len(lines) < _GETSCORES_MIN_HEADER_LINES:
        return GetscoresResponseParseResult(error="expected getscores header response")

    header = _parse_getscores_header(lines)
    if isinstance(header, _ParseError):
        return GetscoresResponseParseResult(error=header.message)

    return GetscoresResponseParseResult(
        response=GetscoresResponse(kind=GetscoresResponseKind.HEADER, header=header)
    )


@dataclass(frozen=True, slots=True)
class _ParseError:
    message: str


def _decode_body(body: bytes) -> str | _ParseError:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        return _ParseError(f"response body is not utf-8: {exc.reason}")


def _parse_key_value_line(line: str) -> Mapping[str, str] | _ParseError:
    fields: dict[str, str] = {}
    for part in line.split("|"):
        if ":" not in part:
            return _ParseError(f"field is missing ':' delimiter: {part}")
        key, value = part.split(":", 1)
        if not key:
            return _ParseError("field key is empty")
        if key in fields:
            return _ParseError(f"duplicate field: {key}")
        fields[key] = value

    return MappingProxyType(fields)


def _parse_chart_line(line: str) -> ScoreSubmitChart | _ParseError:
    fields = _parse_key_value_line(line)
    if isinstance(fields, _ParseError):
        return fields

    chart_id = fields.get("chartId")
    chart_url = fields.get("chartUrl")
    chart_name = fields.get("chartName")
    if chart_id is None or chart_url is None or chart_name is None:
        return _ParseError("chart line is missing chartId, chartUrl, or chartName")

    return ScoreSubmitChart(
        chart_id=chart_id,
        chart_url=chart_url,
        chart_name=chart_name,
        fields=fields,
    )


def _parse_score_submit_metadata(
    fields: Mapping[str, str],
) -> ScoreSubmitBeatmapMetadata | _ParseError:
    required = (
        "beatmapId",
        "beatmapSetId",
        "beatmapPlaycount",
        "beatmapPasscount",
        "approvedDate",
    )
    missing = [field for field in required if field not in fields]
    if missing:
        return _ParseError(f"metadata line is missing fields: {', '.join(missing)}")

    beatmap_id = _parse_int(fields["beatmapId"], "beatmapId")
    if isinstance(beatmap_id, _ParseError):
        return beatmap_id

    beatmapset_id = _parse_int(fields["beatmapSetId"], "beatmapSetId")
    if isinstance(beatmapset_id, _ParseError):
        return beatmapset_id

    playcount = _parse_int(fields["beatmapPlaycount"], "beatmapPlaycount")
    if isinstance(playcount, _ParseError):
        return playcount

    passcount = _parse_int(fields["beatmapPasscount"], "beatmapPasscount")
    if isinstance(passcount, _ParseError):
        return passcount

    return ScoreSubmitBeatmapMetadata(
        beatmap_id=beatmap_id,
        beatmapset_id=beatmapset_id,
        beatmap_playcount=playcount,
        beatmap_passcount=passcount,
        approved_date=fields["approvedDate"],
    )


def _parse_getscores_header(lines: list[str]) -> GetscoresHeader | _ParseError:
    parts = lines[0].split("|")
    if len(parts) < _GETSCORES_MIN_HEADER_FIELDS:
        return _ParseError("getscores header has too few fields")

    status = _parse_int(parts[0], "status")
    failed = _parse_stable_bool(parts[1], "failed")
    beatmap_id = _parse_int(parts[2], "beatmap_id")
    beatmapset_id = _parse_int(parts[3], "beatmapset_id")
    score_count = _parse_int(parts[4], "score_count")
    offset = _parse_int(lines[1], "offset")
    rating = _parse_int(lines[3], "rating")
    error = _first_parse_error(
        status,
        failed,
        beatmap_id,
        beatmapset_id,
        score_count,
        offset,
        rating,
    )
    if error is not None:
        return error

    personal_best_row = _personal_best_row(lines)
    score_rows = tuple(line for line in lines[5:] if line)
    score_rows_error = _score_rows_error(
        score_count=cast("int", score_count),
        personal_best_row=personal_best_row,
        score_rows=score_rows,
    )
    if score_rows_error is not None:
        return score_rows_error

    return GetscoresHeader(
        status=cast("int", status),
        failed=cast("bool", failed),
        beatmap_id=cast("int", beatmap_id),
        beatmapset_id=cast("int", beatmapset_id),
        score_count=cast("int", score_count),
        offset=cast("int", offset),
        display_line=lines[2],
        rating=cast("int", rating),
        personal_best_row=personal_best_row,
        score_rows=score_rows,
    )


def _personal_best_row(lines: list[str]) -> str | None:
    if (
        len(lines) <= _GETSCORES_PERSONAL_BEST_LINE_INDEX
        or not lines[_GETSCORES_PERSONAL_BEST_LINE_INDEX]
    ):
        return None
    return lines[_GETSCORES_PERSONAL_BEST_LINE_INDEX]


def _score_rows_error(
    *,
    score_count: int,
    personal_best_row: str | None,
    score_rows: tuple[str, ...],
) -> _ParseError | None:
    if score_count != len(score_rows):
        return _ParseError("getscores header score_count does not match score rows")
    if personal_best_row is not None and not _is_valid_getscores_score_row(personal_best_row):
        return _ParseError("getscores personal best row has invalid field grammar")
    if any(not _is_valid_getscores_score_row(row) for row in score_rows):
        return _ParseError("getscores score row has invalid field grammar")
    return None


def _is_valid_getscores_score_row(row: str) -> bool:
    fields = row.split("|")
    if len(fields) != _GETSCORES_SCORE_ROW_FIELD_COUNT or not fields[1]:
        return False
    if any(
        not _is_ascii_decimal_integer(fields[index])
        for index in _GETSCORES_SCORE_ROW_NUMERIC_FIELD_INDICES
    ):
        return False
    return all(fields[index] in {"0", "1"} for index in _GETSCORES_SCORE_ROW_BOOLEAN_FIELD_INDICES)


def _is_ascii_decimal_integer(value: str) -> bool:
    return bool(value) and value.isascii() and value.isdecimal()


def _first_parse_error(*values: int | bool | _ParseError) -> _ParseError | None:
    for value in values:
        if isinstance(value, _ParseError):
            return value

    return None


def _parse_int(value: str, field_name: str) -> int | _ParseError:
    try:
        return int(value)
    except ValueError:
        return _ParseError(f"{field_name} is not an integer")


def _parse_stable_bool(value: str, field_name: str) -> bool | _ParseError:
    match value:
        case "true":
            return True
        case "false":
            return False
        case _:
            return _ParseError(f"{field_name} is not a stable bool")


__all__ = [
    "GetscoresHeader",
    "GetscoresResponse",
    "GetscoresResponseKind",
    "GetscoresResponseParseResult",
    "ScoreSubmitBeatmapMetadata",
    "ScoreSubmitChart",
    "ScoreSubmitResponse",
    "ScoreSubmitResponseParseResult",
    "parse_getscores_response",
    "parse_score_submit_response",
]
