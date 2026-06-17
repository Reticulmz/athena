"""Stable legacy score submit mapper tests."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

from athena_cli.stable_verification.parsers import parse_score_submit_response
from osu_server.domain.scores.personal_best import PersonalBestDelta
from osu_server.services.commands.scores import SubmissionOutcome, SubmissionResult
from osu_server.transports.stable.web_legacy.mappers import (
    StableScoreSubmitMapper,
)

_BEATMAP_CHART_REQUIRED_FIELDS = (
    "achieved",
    "rankBefore",
    "rankedScoreBefore",
    "rankedScoreAfter",
    "maxComboAfter",
    "accuracyAfter",
    "ppAfter",
    "onlineScoreId",
)
_OVERALL_CHART_REQUIRED_FIELDS = (
    "rankBefore",
    "rankedScoreBefore",
    "rankedScoreAfter",
    "totalScoreBefore",
    "totalScoreAfter",
    "maxComboAfter",
    "accuracyAfter",
    "ppAfter",
    "achievements-new",
    "onlineScoreId",
)


def _valid_multipart_body() -> bytes:
    encrypted_payload = base64.b64encode(b"encrypted_payload_data")
    iv = base64.b64encode(b"0" * 32)

    return b"".join(
        (
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="score"\r\n\r\n',
            encrypted_payload,
            b"\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="iv"\r\n\r\n',
            iv,
            b"\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="pass"\r\n\r\n',
            b"password_md5_hash\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="x"\r\n\r\n',
            b"client_hash\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="ft"\r\n\r\n',
            b"0\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="osuver"\r\n\r\n',
            b"20241201\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="token"\r\n\r\n',
            b"session_token\r\n",
            b"------WebKitFormBoundary\r\n",
            b'Content-Disposition: form-data; name="score"\r\n\r\n',
            b"replay_binary_data\r\n",
            b"------WebKitFormBoundary--\r\n",
        )
    )


def test_score_submit_mapper_converts_multipart_to_command_input() -> None:
    mapper = StableScoreSubmitMapper()
    submitted_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    command_input = mapper.to_command_input(
        body=_valid_multipart_body(),
        content_type="multipart/form-data; boundary=----WebKitFormBoundary",
        submitted_at=submitted_at,
    )

    assert command_input.encrypted_payload == b"encrypted_payload_data"
    assert command_input.iv == b"0" * 32
    assert command_input.password_md5 == "password_md5_hash"
    assert command_input.client_hash == "client_hash"
    assert command_input.fail_time_ms == 0
    assert command_input.osu_version == "20241201"
    assert command_input.submitted_at == submitted_at
    assert command_input.submission_metadata == {"token": "session_token"}


def test_score_submit_mapper_formats_completed_response() -> None:
    mapper = StableScoreSubmitMapper()

    response = mapper.to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12345,
            beatmap_id=654,
            beatmapset_id=321,
            score=7654321,
            max_combo=987,
            accuracy=0.956789,
            passed=True,
            stable_pp=248,
        )
    )

    assert response.status_code == 200
    body = bytes(response.body)
    parsed = parse_score_submit_response(body)
    lines = body.splitlines()
    assert lines[0] == (
        b"beatmapId:654|beatmapSetId:321|beatmapPlaycount:1|beatmapPasscount:1|approvedDate:"
    )
    assert lines[1].startswith(b"chartId:beatmap|chartUrl:|chartName:Beatmap Ranking|")
    assert b"rankedScoreAfter:7654321" in lines[1]
    assert b"maxComboAfter:987" in lines[1]
    assert b"accuracyAfter:95.6789" in lines[1]
    assert b"ppAfter:248" in lines[1]
    assert b"onlineScoreId:12345" in lines[1]
    assert lines[2].startswith(b"chartId:overall|chartUrl:|chartName:Overall Ranking|")
    assert b"achievements-new:" in lines[2]
    assert b"password_md5_hash" not in body
    assert b"session_token" not in body
    assert b"replay_binary_data" not in body
    assert parsed.response is not None
    assert parsed.response.beatmap_chart.fields["achieved"] == "true"
    for field in _BEATMAP_CHART_REQUIRED_FIELDS:
        assert field in parsed.response.beatmap_chart.fields
    for field in _OVERALL_CHART_REQUIRED_FIELDS:
        assert field in parsed.response.overall_chart.fields


def test_score_submit_mapper_formats_personal_best_delta_values() -> None:
    mapper = StableScoreSubmitMapper()

    response = mapper.to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12346,
            beatmap_id=654,
            beatmapset_id=321,
            score=1000000,
            max_combo=500,
            accuracy=0.9,
            passed=True,
            stable_pp=111,
            stable_pp_before=222,
            stable_pp_after=222,
            personal_best_delta=PersonalBestDelta(
                before_score_id=10,
                before_score=2000000,
                before_max_combo=700,
                before_accuracy=0.98,
                after_score_id=10,
                after_score=2000000,
                after_max_combo=700,
                after_accuracy=0.98,
                updated=False,
            ),
        )
    )

    parsed = parse_score_submit_response(bytes(response.body))

    assert parsed.response is not None
    beatmap_chart = parsed.response.beatmap_chart.fields
    assert beatmap_chart["rankedScoreBefore"] == "2000000"
    assert beatmap_chart["rankedScoreAfter"] == "2000000"
    assert beatmap_chart["maxComboBefore"] == "700"
    assert beatmap_chart["maxComboAfter"] == "700"
    assert beatmap_chart["accuracyBefore"] == "98"
    assert beatmap_chart["accuracyAfter"] == "98"
    assert beatmap_chart["ppBefore"] == "222"
    assert beatmap_chart["ppAfter"] == "222"
    assert beatmap_chart["onlineScoreId"] == "12346"


def test_score_submit_mapper_formats_failed_score_passcount_as_zero() -> None:
    mapper = StableScoreSubmitMapper()

    response = mapper.to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12345,
            beatmap_id=654,
            beatmapset_id=321,
            score=123456,
            max_combo=42,
            accuracy=0.5,
            passed=False,
            stable_pp=None,
        )
    )

    assert response.status_code == 200
    body = bytes(response.body)
    parsed = parse_score_submit_response(body)
    lines = body.splitlines()
    assert lines[0] == (
        b"beatmapId:654|beatmapSetId:321|beatmapPlaycount:1|beatmapPasscount:0|approvedDate:"
    )
    assert parsed.response is not None
    assert parsed.response.beatmap_metadata.beatmap_passcount == 0
    assert parsed.response.beatmap_chart.fields["achieved"] == "false"


def test_score_submit_mapper_formats_completed_response_without_pp_as_zero() -> None:
    mapper = StableScoreSubmitMapper()

    response = mapper.to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12345,
            beatmap_id=654,
            beatmapset_id=321,
            stable_pp=None,
            error_reason="performance_unavailable: calculator stack trace",
        )
    )

    assert response.status_code == 200
    body = bytes(response.body)
    assert b"ppAfter:0" in body
    assert b"performance_unavailable" not in body
    assert b"calculator" not in body
    assert b"stack trace" not in body


def test_score_submit_mapper_formats_rejection_and_retry_responses() -> None:
    mapper = StableScoreSubmitMapper()

    retryable = mapper.to_response(
        SubmissionResult(outcome=SubmissionOutcome.RETRYABLE, error_reason="temporary")
    )
    terminal = mapper.to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.TERMINAL_REJECTED,
            error_reason="rejected",
        )
    )

    assert retryable.body == b"error: yes"
    assert terminal.body == b"error: no"
    assert b"temporary" not in retryable.body
    assert b"rejected" not in terminal.body
