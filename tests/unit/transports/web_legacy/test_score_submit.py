"""Unit tests for score submit handler."""

# pyright: reportArgumentType=false

import base64
from typing import Protocol

import pytest
import structlog.testing
from starlette.datastructures import Headers
from starlette.responses import Response

from osu_server.services.commands.scores import (
    ParsedSubmissionInput,
    SubmissionOutcome,
    SubmissionResult,
)
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler


class ProcessScoreSubmissionUseCaseProtocol(Protocol):
    """Protocol for score submission service."""

    async def execute(self, input_data: ParsedSubmissionInput) -> SubmissionResult: ...


class StubProcessScoreSubmissionUseCase:
    """Stub service for testing."""

    def __init__(self, result: SubmissionResult) -> None:
        self._result: SubmissionResult = result
        self.last_input: ParsedSubmissionInput | None = None

    async def execute(self, input_data: ParsedSubmissionInput) -> SubmissionResult:
        self.last_input = input_data
        return self._result


class StubRequest:
    """Stub request for testing."""

    def __init__(self, body_data: bytes, content_type: str) -> None:
        self.headers: Headers = Headers({"content-type": content_type})
        self._body: bytes = body_data

    async def body(self) -> bytes:
        return self._body


@pytest.fixture
def valid_multipart_body() -> bytes:
    """Valid multipart request body fixture."""
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


@pytest.fixture
def mock_request(valid_multipart_body: bytes) -> StubRequest:
    """Mock Starlette request."""
    return StubRequest(
        valid_multipart_body, "multipart/form-data; boundary=----WebKitFormBoundary"
    )


@pytest.mark.asyncio
async def test_handle_score_submit_completed(mock_request: StubRequest) -> None:
    """Test completed response format."""
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12345,
        )
    )
    handler = ScoreSubmitHandler(service)

    with structlog.testing.capture_logs() as cap_logs:
        response = await handler(mock_request)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert b":" in response.body
    assert b"chartId:" in response.body
    assert service.last_input is not None
    assert service.last_input.beatmap_id is None
    assert service.last_input.submission_metadata == {"token": "session_token"}
    assert any(
        entry["event"] == "score_submission_multipart_parsed"
        and entry["score_field_count"] == 2
        and entry["replay_present"] is True
        and entry["replay_byte_size"] == len(b"replay_binary_data")
        for entry in cap_logs
    )


@pytest.mark.asyncio
async def test_handle_score_submit_terminal_reject(mock_request: StubRequest) -> None:
    """Test terminal reject response format."""
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(
            outcome=SubmissionOutcome.TERMINAL_REJECTED,
            error_reason="authorization_failure",
        )
    )
    handler = ScoreSubmitHandler(service)

    with structlog.testing.capture_logs() as cap_logs:
        response = await handler(mock_request)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.body == b"error: no"
    assert any(
        entry["event"] == "score_submission_terminal_response"
        and entry["error_reason"] == "authorization_failure"
        for entry in cap_logs
    )


@pytest.mark.asyncio
async def test_handle_score_submit_retryable(mock_request: StubRequest) -> None:
    """Test retryable response format."""
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(
            outcome=SubmissionOutcome.RETRYABLE,
            error_reason="temporary_error",
        )
    )
    handler = ScoreSubmitHandler(service)

    response = await handler(mock_request)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.body == b"error: yes"


@pytest.mark.asyncio
async def test_handle_score_submit_parsing_error(valid_multipart_body: bytes) -> None:
    """Test parsing error returns terminal reject."""
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(outcome=SubmissionOutcome.COMPLETED, score_id=1)
    )
    handler = ScoreSubmitHandler(service)

    request = StubRequest(valid_multipart_body, "text/plain")

    with structlog.testing.capture_logs() as cap_logs:
        response = await handler(request)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.body == b"error: no"
    assert any(
        entry["event"] == "score_submission_failed" and entry["reason"] == "multipart_parse_failed"
        for entry in cap_logs
    )
