"""POST /web/osu-submit-modular-selector.php — stable client score submission handler."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from starlette.responses import Response

from osu_server.infrastructure.parsers.multipart_parser import MultipartLimits, ParseError, parse
from osu_server.services.commands.scores import (
    ParsedSubmissionInput,
    ProcessScoreSubmissionUseCase,
    SubmissionOutcome,
)

if TYPE_CHECKING:
    from starlette.requests import Request

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class ScoreSubmitHandler:
    """Handler for POST /web/osu-submit-modular-selector.php.

    Stable client score submission endpoint.
    """

    def __init__(
        self,
        submit_score_command: ProcessScoreSubmissionUseCase,
        limits: MultipartLimits | None = None,
    ) -> None:
        self._submit_score_command: ProcessScoreSubmissionUseCase = submit_score_command
        self._limits: MultipartLimits = limits or MultipartLimits()

    async def __call__(self, request: Request) -> Response:
        """Handle score submission request.

        Requirements: R1.1, R2.1-2.5, R10.1-10.5
        """
        try:
            body = await request.body()
            content_type = request.headers.get("content-type", "")
            parsed = parse(body, content_type, self._limits)
        except ParseError as exc:
            logger.warning(
                "score_submission_failed",
                reason="multipart_parse_failed",
                error=str(exc),
            )
            return Response(b"error: no", status_code=200)

        logger.debug(
            "score_submission_multipart_parsed",
            score_field_count=parsed.score_field_count,
            replay_present=parsed.replay_data is not None,
            replay_byte_size=len(parsed.replay_data) if parsed.replay_data is not None else None,
            fail_time_ms=parsed.fail_time_ms,
            osu_version=parsed.osu_version,
        )

        input_data = ParsedSubmissionInput(
            encrypted_payload=parsed.encrypted_payload,
            iv=parsed.iv,
            replay_data=parsed.replay_data,
            password_md5=parsed.password_md5,
            client_hash=parsed.client_hash,
            fail_time_ms=parsed.fail_time_ms,
            osu_version=parsed.osu_version,
            submitted_at=datetime.now(UTC),
            submission_metadata=parsed.submission_metadata,
        )

        result = await self._submit_score_command.execute(input_data)

        if result.outcome == SubmissionOutcome.COMPLETED:
            return _format_completed_response(
                beatmap_id=result.beatmap_id or 0,
                beatmap_set_id=result.beatmapset_id or 0,
            )
        if result.outcome == SubmissionOutcome.RETRYABLE:
            logger.info(
                "score_submission_retryable_response",
                error_reason=result.error_reason,
            )
            return Response(b"error: yes", status_code=200)
        if result.outcome == SubmissionOutcome.ACCEPTED_PENDING:
            logger.info(
                "score_submission_pending_response",
                error_reason=result.error_reason,
            )
            return Response(b"error: yes", status_code=200)
        logger.warning(
            "score_submission_terminal_response",
            error_reason=result.error_reason,
        )
        return Response(b"error: no", status_code=200)


def _format_completed_response(*, beatmap_id: int, beatmap_set_id: int) -> Response:
    """Format completed response in stable client format.

    Format: beatmapId:beatmapSetId:beatmapPlaycount:3\\nchart...
    Requirements: R10.1, R10.5

    Note: PP calculation and leaderboard ranks are deferred to later waves.
    """
    beatmap_playcount = 1

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
    body += b"pp:0\n"

    return Response(body, status_code=200)
