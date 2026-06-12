"""POST /web/osu-submit-modular-selector.php — stable client score submission handler."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from starlette.responses import Response

from osu_server.infrastructure.parsers.multipart_parser import ParseError, parse
from osu_server.services.score_submission_service import (
    ParsedSubmissionInput,
    SubmissionOutcome,
)

if TYPE_CHECKING:
    from starlette.requests import Request

    from osu_server.services.score_submission_service import ScoreSubmissionService


async def handle_score_submit(
    request: Request,
    service: ScoreSubmissionService,
) -> Response:
    """Handle POST /web/osu-submit-modular-selector.php.

    Requirements: R1.1, R2.1-2.5, R10.1-10.5
    """
    try:
        body = await request.body()
        content_type = request.headers.get("content-type", "")
        parsed = parse(body, content_type)
    except ParseError:
        return Response(b"error: no", status_code=200)

    input_data = ParsedSubmissionInput(
        encrypted_payload=parsed.encrypted_payload,
        iv=parsed.iv,
        replay_data=parsed.replay_data,
        password_md5=parsed.password_md5,
        client_hash=parsed.client_hash,
        fail_time_ms=parsed.fail_time_ms,
        osu_version=parsed.osu_version,
        beatmap_id=0,  # Extracted from decrypted payload in service layer
        submitted_at=datetime.now(UTC),
    )

    result = await service.submit_score(input_data)

    if result.outcome == SubmissionOutcome.COMPLETED:
        return _format_completed_response(result.score_id or 0)
    if result.outcome == SubmissionOutcome.RETRYABLE:
        return Response(b"error: yes", status_code=200)
    return Response(b"error: no", status_code=200)


def _format_completed_response(_score_id: int) -> Response:
    """Format completed response in stable client format.

    Format: beatmapId:beatmapSetId:beatmapPlaycount:3\\nchart...
    Requirements: R10.1, R10.5

    Note: score_id is accepted but not used in Wave 1 (PP calculation deferred to Wave 2).
    """
    beatmap_id = 0
    beatmap_set_id = 0
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
