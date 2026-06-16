"""Stable legacy score submit mapper tests."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

from osu_server.services.commands.scores import SubmissionOutcome, SubmissionResult
from osu_server.transports.stable.web_legacy.mappers import (
    StableScoreSubmitMapper,
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
            stable_pp=248,
        )
    )

    assert response.status_code == 200
    body = bytes(response.body)
    assert body.startswith(b"654:321:1:3\n")
    assert b"chartId:overall\n" in body
    assert b"pp:248\n" in body


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
    assert b"pp:0\n" in body
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
