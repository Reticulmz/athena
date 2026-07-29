"""Stable getscoresとscore submitのtext responseを構造化するparserを提供する."""

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
    """Getscores response bodyのwire shapeを表す.

    Attributes:
        NOT_SUBMITTED (str): Scoreが未送信である短縮response.
        UPDATE_AVAILABLE (str): Client updateを要求する短縮response.
        HEADER (str): Leaderboard headerとscore rowを持つresponse.
    """

    NOT_SUBMITTED = "not_submitted"
    UPDATE_AVAILABLE = "update_available"
    HEADER = "header"


@dataclass(frozen=True, slots=True)
class ScoreSubmitBeatmapMetadata:
    """Score submit completed responseのbeatmap metadataを表す.

    Attributes:
        beatmap_id (int): `beatmapId` fieldのbeatmap ID.
        beatmapset_id (int): `beatmapSetId` fieldのbeatmapset ID.
        beatmap_playcount (int): `beatmapPlaycount` fieldの再生回数.
        beatmap_passcount (int): `beatmapPasscount` fieldの完走回数.
        approved_date (str): `approvedDate` fieldの原文値.
    """

    beatmap_id: int
    beatmapset_id: int
    beatmap_playcount: int
    beatmap_passcount: int
    approved_date: str


@dataclass(frozen=True, slots=True)
class ScoreSubmitChart:
    """Score submit completed responseのchart sectionを表す.

    Attributes:
        chart_id (str): `chartId` fieldのsection識別子.
        chart_url (str): `chartUrl` fieldの参照URL.
        chart_name (str): `chartName` fieldの表示名.
        fields (Mapping[str, str]): Sectionに含まれるすべてのkey-value field.
    """

    chart_id: str
    chart_url: str
    chart_name: str
    fields: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ScoreSubmitResponse:
    """正常完了したscore submit responseを表す.

    Attributes:
        beatmap_metadata (ScoreSubmitBeatmapMetadata): Beatmap metadata section.
        beatmap_chart (ScoreSubmitChart): Beatmap ranking chart section.
        overall_chart (ScoreSubmitChart): Overall ranking chart section.
    """

    beatmap_metadata: ScoreSubmitBeatmapMetadata
    beatmap_chart: ScoreSubmitChart
    overall_chart: ScoreSubmitChart

    @property
    def achievement_notification(self) -> str | None:
        """`achievements-new` fieldの通知内容を返す.

        Returns:
            str | None: Overall chartに含まれるachievement通知.fieldがなければNone.
        """
        return self.overall_chart.fields.get("achievements-new")


@dataclass(frozen=True, slots=True)
class ScoreSubmitResponseParseResult:
    """Score submit responseのparse成功または失敗を表す.

    Attributes:
        response (ScoreSubmitResponse | None): 成功時の構造化response.失敗時はNone.
        error (str | None): 失敗時のreport-safeな理由.成功時はNone.
    """

    response: ScoreSubmitResponse | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class GetscoresHeader:
    """Getscores headerとleaderboard rowを表す.

    Attributes:
        status (int): Header先頭fieldのstatus値.
        failed (bool): Headerの`failed` fieldを変換した値.
        beatmap_id (int): 対象beatmap ID.
        beatmapset_id (int): 対象beatmapset ID.
        score_count (int): Personal Bestを除くleaderboard row数.
        offset (int): Leaderboardのoffset値.
        display_line (str): Client表示用のbeatmap text line.
        rating (int): Headerに含まれるrating値.
        personal_best_row (str | None): Personal Best row.存在しない場合はNone.
        score_rows (tuple[str, ...]): Personal Bestを除くleaderboard score row.
    """

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
        """Leaderboardにscore rowが存在しないかを返す.

        Returns:
            bool: `score_count`が0でscore rowも空の場合はTrue.
        """
        return self.score_count == 0 and not self.score_rows


@dataclass(frozen=True, slots=True)
class GetscoresResponse:
    """Getscores responseのkindと任意headerを表す.

    Attributes:
        kind (GetscoresResponseKind): Response bodyのwire shape.
        header (GetscoresHeader | None): Header responseの解析結果.短縮responseではNone.
    """

    kind: GetscoresResponseKind
    header: GetscoresHeader | None = None


@dataclass(frozen=True, slots=True)
class GetscoresResponseParseResult:
    """Getscores responseのparse成功または失敗を表す.

    Attributes:
        response (GetscoresResponse | None): 成功時の構造化response.失敗時はNone.
        error (str | None): 失敗時のreport-safeな理由.成功時はNone.
    """

    response: GetscoresResponse | None = None
    error: str | None = None


def parse_score_submit_response(body: bytes) -> ScoreSubmitResponseParseResult:
    """Score submit completed responseをwire grammarに従って構造化する.

    Args:
        body (bytes): Stable score submit endpointから受け取ったresponse body.

    Returns:
        ScoreSubmitResponseParseResult: Metadataと2つのchart sectionを解析した結果.形式不正は
            `error`へ格納する.

    Notes:
        正常responseはmetadata lineとbeatmap/overall chart lineの3行である.
    """
    text_result = _decode_body(body)
    if isinstance(text_result, _ParseError):
        return ScoreSubmitResponseParseResult(error=text_result.message)

    lines = text_result.splitlines()
    if len(lines) != _SCORE_SUBMIT_COMPLETED_LINE_COUNT:
        return ScoreSubmitResponseParseResult(error="expected completed score submit response")

    return _parse_score_submit_lines(lines)


def _parse_score_submit_lines(lines: list[str]) -> ScoreSubmitResponseParseResult:
    """3行へ分割済みのscore submit responseを構造化する.

    Args:
        lines (list[str]): Metadata lineと2つのchart lineを順番に持つ3行のresponse.

    Returns:
        ScoreSubmitResponseParseResult: 全sectionの解析結果.field不正は`error`へ格納する.
    """
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
    """Getscores response bodyをwire grammarまで検証して構造化する.

    Args:
        body (bytes): Stable getscores endpointから受け取ったresponse body.

    Returns:
        GetscoresResponseParseResult: Short responseまたはheader / score rowを検証した結果.形式
            不正は`error`へ格納する.

    Notes:
        Headerの`score_count`はPersonal Bestを含めずleaderboard row数と一致する必要がある.
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
    """Parser内部でwire grammarの不正を伝える値を表す.

    Attributes:
        message (str): Report-safeなparse失敗理由.
    """

    message: str


def _decode_body(body: bytes) -> str | _ParseError:
    """Response bodyをUTF-8 textへ復号する.

    Args:
        body (bytes): 復号するresponse body.

    Returns:
        str | _ParseError: 成功時のUTF-8 text.復号不能時は理由を持つparse error.
    """
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        return _ParseError(f"response body is not utf-8: {exc.reason}")


def _parse_key_value_line(line: str) -> Mapping[str, str] | _ParseError:
    """`key:value` fieldを`|`区切りで持つlineをmappingへ変換する.

    Args:
        line (str): Score submit metadataまたはchart sectionのwire line.

    Returns:
        Mapping[str, str] | _ParseError: 重複しないfield mapping.delimiterまたはkey不正時は
            parse error.
    """
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
    """Score submit chart lineを必須field付きのchartへ変換する.

    Args:
        line (str): `chartId`,`chartUrl`,`chartName`を含むchart wire line.

    Returns:
        ScoreSubmitChart | _ParseError: 必須chart fieldを持つchart.field不足時はparse error.
    """
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
    """Score submit metadata fieldを型付きbeatmap metadataへ変換する.

    Args:
        fields (Mapping[str, str]): Metadata lineから抽出したkey-value field.

    Returns:
        ScoreSubmitBeatmapMetadata | _ParseError: 必須fieldを整数へ変換したmetadata.
            Field不足または数値不正時はparse error.
    """
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
    """Getscores headerとscore rowを検証して構造化する.

    Args:
        lines (list[str]): Short response以外のgetscores bodyを行単位で分割した値.

    Returns:
        GetscoresHeader | _ParseError: HeaderとPersonal Best/leaderboard row.field数または
            wire grammar不正時はparse error.
    """
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
    """Getscores responseからPersonal Best rowを取り出す.

    Args:
        lines (list[str]): Getscores bodyを行単位で分割した値.

    Returns:
        str | None: 5行目のPersonal Best row.行がないか空文字列ならNone.
    """
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
    """Leaderboard row数と各rowのwire grammarを検証する.

    Args:
        score_count (int): Headerが宣言するleaderboard row数.
        personal_best_row (str | None): 任意のPersonal Best row.
        score_rows (tuple[str, ...]): Personal Bestを除くleaderboard row.

    Returns:
        _ParseError | None: 不整合時のparse error.すべて有効ならNone.
    """
    if score_count != len(score_rows):
        return _ParseError("getscores header score_count does not match score rows")
    if personal_best_row is not None and not _is_valid_getscores_score_row(personal_best_row):
        return _ParseError("getscores personal best row has invalid field grammar")
    if any(not _is_valid_getscores_score_row(row) for row in score_rows):
        return _ParseError("getscores score row has invalid field grammar")
    return None


def _is_valid_getscores_score_row(row: str) -> bool:
    """Getscores score rowが定義済みfield grammarを満たすか判定する.

    Args:
        row (str): `|`区切りのscore row.

    Returns:
        bool: Field数,必須username,数値field,boolean fieldがすべて有効ならTrue.
    """
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
    """文字列がASCII decimal integerかを判定する.

    Args:
        value (str): 判定する文字列.

    Returns:
        bool: 空文字列でなくASCII decimal digitだけで構成される場合はTrue.
    """
    return bool(value) and value.isascii() and value.isdecimal()


def _first_parse_error(*values: int | bool | _ParseError) -> _ParseError | None:
    """値列に含まれる最初のparse errorを返す.

    Args:
        *values (int | bool | _ParseError): 変換結果またはparse errorの列.

    Returns:
        _ParseError | None: 最初に見つかったparse error.存在しない場合はNone.
    """
    for value in values:
        if isinstance(value, _ParseError):
            return value

    return None


def _parse_int(value: str, field_name: str) -> int | _ParseError:
    """Wire fieldを整数へ変換する.

    Args:
        value (str): 変換するwire fieldの文字列値.
        field_name (str): 失敗診断へ含めるfield名.

    Returns:
        int | _ParseError: 変換済み整数.整数でない場合はparse error.
    """
    try:
        return int(value)
    except ValueError:
        return _ParseError(f"{field_name} is not an integer")


def _parse_stable_bool(value: str, field_name: str) -> bool | _ParseError:
    """Stable wireの`true`または`false`をboolへ変換する.

    Args:
        value (str): 変換するwire fieldの文字列値.
        field_name (str): 失敗診断へ含めるfield名.

    Returns:
        bool | _ParseError: `true`または`false`の変換結果.それ以外はparse error.
    """
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
