"""Stable legacy score submit request and response mappers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP
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
    BeatmapRankDelta,
    ParsedSubmissionInput,
    SubmissionOutcome,
    SubmissionResult,
)

if TYPE_CHECKING:
    from osu_server.domain.scores.personal_best import PersonalBestDelta
    from osu_server.domain.scores.user_stats import UserCurrentStats

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
    submit_exit_classification: str | None
    osu_version: str | None


@dataclass(frozen=True, slots=True)
class StableScoreSubmitOverallStats:
    """Stable score submit overall chart に載せる current stats 値。"""

    rank: int | None = None
    ranked_score: int = 0
    total_score: int = 0
    max_combo: int = 0
    accuracy: float = 0.0
    stable_pp: int = 0


@dataclass(frozen=True, slots=True)
class _BeatmapMetadataFields:
    beatmap_id: int
    beatmapset_id: int
    playcount: int
    passcount: int
    approved_at: datetime | None


@dataclass(frozen=True, slots=True)
class _BeatmapChartFields:
    chart_url: str
    achieved: str
    rank_before: int | str
    rank_after: int
    max_combo_before: int
    max_combo_after: int
    accuracy_before: str
    accuracy_after: str
    score_before: int
    score_after: int
    pp_before: int
    pp_after: int
    score_id: int


@dataclass(frozen=True, slots=True)
class _OverallChartFields:
    chart_url: str
    rank_before: int
    rank_after: int
    ranked_score_before: int
    ranked_score_after: int
    total_score_before: int
    total_score_after: int
    max_combo_before: int
    max_combo_after: int
    accuracy_before: str
    accuracy_after: str
    pp_before: int
    pp_after: int
    score_id: int


class StableScoreSubmitMapper:
    """Map stable legacy score submit wire data to command inputs and responses."""

    def __init__(
        self,
        limits: MultipartLimits | None = None,
        stable_web_base_url: str = "",
    ) -> None:
        self._limits: MultipartLimits = limits or MultipartLimits()
        self._stable_web_base_url: str = stable_web_base_url.rstrip("/")

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
            submit_exit_classification=parsed.submit_exit_classification,
            submission_metadata=parsed.submission_metadata,
        )
        return StableScoreSubmitCommandMapping(
            input_data=input_data,
            score_field_count=parsed.score_field_count,
            replay_present=parsed.replay_data is not None,
            replay_byte_size=len(parsed.replay_data) if parsed.replay_data is not None else None,
            fail_time_ms=parsed.fail_time_ms,
            submit_exit_classification=parsed.submit_exit_classification,
            osu_version=parsed.osu_version,
        )

    def to_response(
        self,
        result: SubmissionResult,
        *,
        overall_stats: StableScoreSubmitOverallStats | None = None,
    ) -> Response:
        """submission result を stable legacy response body へ変換する。"""
        if result.outcome == SubmissionOutcome.COMPLETED:
            return _format_completed_response(
                result,
                overall_stats_after=overall_stats
                or _score_submit_overall_stats(result.overall_stats_after),
                stable_web_base_url=self._stable_web_base_url,
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
    result: SubmissionResult,
    *,
    overall_stats_after: StableScoreSubmitOverallStats | None,
    stable_web_base_url: str,
) -> Response:
    overall_stats_before = _score_submit_overall_stats(result.overall_stats_before)
    body = "\n".join(
        (
            _format_beatmap_metadata_line(_beatmap_metadata_fields(result)),
            _format_beatmap_chart_line(
                _beatmap_chart_fields(
                    result,
                    stable_web_base_url=stable_web_base_url,
                )
            ),
            _format_overall_chart_line(
                _overall_chart_fields(
                    result,
                    overall_stats_before=overall_stats_before,
                    overall_stats_after=overall_stats_after,
                    stable_web_base_url=stable_web_base_url,
                )
            ),
        )
    )

    return Response(body.encode(), status_code=200)


def _beatmap_metadata_fields(result: SubmissionResult) -> _BeatmapMetadataFields:
    return _BeatmapMetadataFields(
        beatmap_id=result.beatmap_id or 0,
        beatmapset_id=result.beatmapset_id or 0,
        playcount=result.beatmap_playcount if result.beatmap_playcount is not None else 1,
        passcount=_displayed_passcount(result),
        approved_at=result.beatmap_approved_at,
    )


def _displayed_passcount(result: SubmissionResult) -> int:
    if result.beatmap_passcount is not None:
        return result.beatmap_passcount
    return 0 if result.passed is False else 1


def _beatmap_chart_fields(
    result: SubmissionResult,
    *,
    stable_web_base_url: str,
) -> _BeatmapChartFields:
    score_before, max_combo_before, accuracy_before = _score_submit_before_fields(
        result.personal_best_delta,
    )
    score_after, max_combo_after, accuracy_after = _score_submit_after_fields(result)
    rank_before, rank_after = _beatmap_rank_fields(result.beatmap_rank_delta)
    pp_after = (
        result.stable_pp_after if result.stable_pp_after is not None else result.stable_pp or 0
    )

    return _BeatmapChartFields(
        chart_url=_stable_beatmap_url(stable_web_base_url, result.beatmap_id or 0),
        achieved="false" if result.passed is False else "true",
        rank_before=rank_before,
        rank_after=rank_after,
        max_combo_before=max_combo_before,
        max_combo_after=max_combo_after,
        accuracy_before=accuracy_before,
        accuracy_after=accuracy_after,
        score_before=score_before,
        score_after=score_after,
        pp_before=result.stable_pp_before or 0,
        pp_after=pp_after,
        score_id=result.score_id or 0,
    )


def _score_submit_before_fields(
    personal_best_delta: PersonalBestDelta | None,
) -> tuple[int, int, str]:
    if personal_best_delta is None:
        return 0, 0, "0"
    return (
        personal_best_delta.before_score or 0,
        personal_best_delta.before_max_combo or 0,
        _format_accuracy_percent(personal_best_delta.before_accuracy),
    )


def _score_submit_after_fields(result: SubmissionResult) -> tuple[int, int, str]:
    personal_best_delta = result.personal_best_delta
    if personal_best_delta is None:
        return result.score or 0, result.max_combo or 0, _format_accuracy_percent(result.accuracy)
    return (
        personal_best_delta.after_score or 0,
        personal_best_delta.after_max_combo or 0,
        _format_accuracy_percent(personal_best_delta.after_accuracy),
    )


def _beatmap_rank_fields(beatmap_rank_delta: BeatmapRankDelta | None) -> tuple[int | str, int]:
    if beatmap_rank_delta is None:
        return "", 0

    rank_before: int | str = (
        beatmap_rank_delta.before if beatmap_rank_delta.before is not None else ""
    )
    rank_after = beatmap_rank_delta.after if beatmap_rank_delta.after is not None else 0
    return rank_before, rank_after


def _overall_chart_fields(
    result: SubmissionResult,
    *,
    overall_stats_before: StableScoreSubmitOverallStats | None,
    overall_stats_after: StableScoreSubmitOverallStats | None,
    stable_web_base_url: str,
) -> _OverallChartFields:
    before = overall_stats_before or StableScoreSubmitOverallStats()
    after = overall_stats_after or StableScoreSubmitOverallStats()

    return _OverallChartFields(
        chart_url=_stable_user_url(stable_web_base_url, result.user_id or 0),
        rank_before=before.rank or 0,
        rank_after=after.rank or 0,
        ranked_score_before=before.ranked_score,
        ranked_score_after=after.ranked_score,
        total_score_before=before.total_score,
        total_score_after=after.total_score,
        max_combo_before=before.max_combo,
        max_combo_after=after.max_combo,
        accuracy_before=_format_accuracy_percent(before.accuracy),
        accuracy_after=_format_accuracy_percent(after.accuracy),
        pp_before=before.stable_pp,
        pp_after=after.stable_pp,
        score_id=result.score_id or 0,
    )


def _format_beatmap_metadata_line(fields: _BeatmapMetadataFields) -> str:
    return _format_chart_line(
        (
            ("beatmapId", fields.beatmap_id),
            ("beatmapSetId", fields.beatmapset_id),
            ("beatmapPlaycount", fields.playcount),
            ("beatmapPasscount", fields.passcount),
            ("approvedDate", _format_stable_datetime(fields.approved_at)),
        )
    )


def _format_beatmap_chart_line(fields: _BeatmapChartFields) -> str:
    return _format_chart_line(
        (
            ("chartId", "beatmap"),
            ("chartUrl", fields.chart_url),
            ("chartName", "Beatmap Ranking"),
            ("achieved", fields.achieved),
            ("rankBefore", fields.rank_before),
            ("rankAfter", fields.rank_after),
            ("maxComboBefore", fields.max_combo_before),
            ("maxComboAfter", fields.max_combo_after),
            ("accuracyBefore", fields.accuracy_before),
            ("accuracyAfter", fields.accuracy_after),
            ("rankedScoreBefore", fields.score_before),
            ("rankedScoreAfter", fields.score_after),
            ("ppBefore", fields.pp_before),
            ("ppAfter", fields.pp_after),
            ("onlineScoreId", fields.score_id),
        )
    )


def _format_overall_chart_line(fields: _OverallChartFields) -> str:
    return _format_chart_line(
        (
            ("chartId", "overall"),
            ("chartUrl", fields.chart_url),
            ("chartName", "Overall Ranking"),
            ("rankBefore", fields.rank_before),
            ("rankAfter", fields.rank_after),
            ("rankedScoreBefore", fields.ranked_score_before),
            ("rankedScoreAfter", fields.ranked_score_after),
            ("totalScoreBefore", fields.total_score_before),
            ("totalScoreAfter", fields.total_score_after),
            ("maxComboBefore", fields.max_combo_before),
            ("maxComboAfter", fields.max_combo_after),
            ("accuracyBefore", fields.accuracy_before),
            ("accuracyAfter", fields.accuracy_after),
            ("ppBefore", fields.pp_before),
            ("ppAfter", fields.pp_after),
            ("achievements-new", ""),
            ("onlineScoreId", fields.score_id),
        )
    )


def _stable_beatmap_url(stable_web_base_url: str, beatmap_id: int) -> str:
    if not stable_web_base_url or beatmap_id <= 0:
        return ""
    return f"{stable_web_base_url}/b/{beatmap_id}"


def _stable_user_url(stable_web_base_url: str, user_id: int) -> str:
    if not stable_web_base_url or user_id <= 0:
        return ""
    return f"{stable_web_base_url}/u/{user_id}"


def _score_submit_overall_stats(
    current_stats: UserCurrentStats | None,
) -> StableScoreSubmitOverallStats | None:
    if current_stats is None:
        return None
    return StableScoreSubmitOverallStats(
        rank=current_stats.global_rank,
        ranked_score=current_stats.ranked_score,
        total_score=current_stats.total_score,
        max_combo=current_stats.max_combo,
        accuracy=current_stats.accuracy,
        stable_pp=int(current_stats.pp.to_integral_value(rounding=ROUND_HALF_UP)),
    )


def _format_accuracy_percent(accuracy: float | None) -> str:
    if accuracy is None:
        return "0"
    percent = accuracy * 100
    return f"{percent:.6f}".rstrip("0").rstrip(".")


def _format_stable_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    stable_value = value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)
    return stable_value.strftime("%Y-%m-%d %H:%M:%S")


def _format_chart_line(entries: tuple[tuple[str, object], ...]) -> str:
    return "|".join(f"{key}:{value}" for key, value in entries)


__all__ = [
    "MultipartParseError",
    "StableScorePayloadParser",
    "StableScoreSubmitCommandMapping",
    "StableScoreSubmitMapper",
    "StableScoreSubmitOverallStats",
]
