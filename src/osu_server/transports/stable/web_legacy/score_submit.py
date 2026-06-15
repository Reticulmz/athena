"""POST /web/osu-submit-modular-selector.php — stable client score submission handler."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from starlette.responses import Response

from osu_server.services.commands.scores import (
    ProcessScoreSubmissionUseCase,
    SubmissionOutcome,
)
from osu_server.transports.stable.web_legacy.mappers import (
    MultipartParseError,
    StableScoreSubmitMapper,
)

if TYPE_CHECKING:
    from starlette.requests import Request

    from osu_server.infrastructure.parsers.multipart_parser import MultipartLimits

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class ScoreSubmitHandler:
    """Handler for POST /web/osu-submit-modular-selector.php.

    Stable client score submission endpoint.
    """

    def __init__(
        self,
        submit_score_command: ProcessScoreSubmissionUseCase,
        limits: MultipartLimits | None = None,
        mapper: StableScoreSubmitMapper | None = None,
    ) -> None:
        self._submit_score_command: ProcessScoreSubmissionUseCase = submit_score_command
        self._mapper: StableScoreSubmitMapper = mapper or StableScoreSubmitMapper(limits)

    async def __call__(self, request: Request) -> Response:
        """Handle score submission request.

        Requirements: R1.1, R2.1-2.5, R10.1-10.5
        """
        try:
            body = await request.body()
            content_type = request.headers.get("content-type", "")
            command_mapping = self._mapper.to_command_mapping(
                body=body,
                content_type=content_type,
                submitted_at=datetime.now(UTC),
            )
        except MultipartParseError as exc:
            logger.warning(
                "score_submission_failed",
                reason="multipart_parse_failed",
                error=str(exc),
            )
            return Response(b"error: no", status_code=200)

        logger.debug(
            "score_submission_multipart_parsed",
            score_field_count=command_mapping.score_field_count,
            replay_present=command_mapping.replay_present,
            replay_byte_size=command_mapping.replay_byte_size,
            fail_time_ms=command_mapping.fail_time_ms,
            osu_version=command_mapping.osu_version,
        )

        input_data = command_mapping.input_data
        result = await self._submit_score_command.execute(input_data)

        if result.outcome == SubmissionOutcome.COMPLETED:
            return self._mapper.to_response(result)
        if result.outcome == SubmissionOutcome.RETRYABLE:
            logger.info(
                "score_submission_retryable_response",
                error_reason=result.error_reason,
            )
            return self._mapper.to_response(result)
        if result.outcome == SubmissionOutcome.ACCEPTED_PENDING:
            logger.info(
                "score_submission_pending_response",
                error_reason=result.error_reason,
            )
            return self._mapper.to_response(result)
        logger.warning(
            "score_submission_terminal_response",
            error_reason=result.error_reason,
        )
        return self._mapper.to_response(result)
