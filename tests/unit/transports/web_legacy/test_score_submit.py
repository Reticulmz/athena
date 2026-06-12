"""Unit tests for score submit handler."""

# pyright: reportArgumentType=false

from typing import Protocol

import pytest
from starlette.datastructures import Headers
from starlette.responses import Response

from osu_server.services.score_submission_service import (
    ParsedSubmissionInput,
    SubmissionOutcome,
    SubmissionResult,
)
from osu_server.transports.web_legacy.score_submit import handle_score_submit


class ScoreSubmissionServiceProtocol(Protocol):
    """Protocol for score submission service."""

    async def submit_score(self, input_data: ParsedSubmissionInput) -> SubmissionResult: ...


class StubScoreSubmissionService:
    """Stub service for testing."""

    def __init__(self, result: SubmissionResult) -> None:
        self._result: SubmissionResult = result

    async def submit_score(self, _input_data: ParsedSubmissionInput) -> SubmissionResult:
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
    return (
        b"------WebKitFormBoundary\r\n"
        b'Content-Disposition: form-data; name="score"\r\n\r\n'
        b"encrypted_payload_data\r\n"
        b"------WebKitFormBoundary\r\n"
        b'Content-Disposition: form-data; name="iv"\r\n\r\n'
        b"iv_data_16bytes_\r\n"
        b"------WebKitFormBoundary\r\n"
        b'Content-Disposition: form-data; name="pass"\r\n\r\n'
        b"password_md5_hash\r\n"
        b"------WebKitFormBoundary\r\n"
        b'Content-Disposition: form-data; name="x"\r\n\r\n'
        b"client_hash\r\n"
        b"------WebKitFormBoundary\r\n"
        b'Content-Disposition: form-data; name="ft"\r\n\r\n'
        b"0\r\n"
        b"------WebKitFormBoundary\r\n"
        b'Content-Disposition: form-data; name="osuver"\r\n\r\n'
        b"20241201\r\n"
        b"------WebKitFormBoundary\r\n"
        b'Content-Disposition: form-data; name="score"\r\n\r\n'
        b"replay_binary_data\r\n"
        b"------WebKitFormBoundary--\r\n"
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
    service = StubScoreSubmissionService(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12345,
        )
    )

    response = await handle_score_submit(mock_request, service)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert b":" in response.body
    assert b"chartId:" in response.body


@pytest.mark.asyncio
async def test_handle_score_submit_terminal_reject(mock_request: StubRequest) -> None:
    """Test terminal reject response format."""
    service = StubScoreSubmissionService(
        SubmissionResult(
            outcome=SubmissionOutcome.TERMINAL_REJECTED,
            error_reason="authorization_failure",
        )
    )

    response = await handle_score_submit(mock_request, service)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.body == b"error: no"


@pytest.mark.asyncio
async def test_handle_score_submit_retryable(mock_request: StubRequest) -> None:
    """Test retryable response format."""
    service = StubScoreSubmissionService(
        SubmissionResult(
            outcome=SubmissionOutcome.RETRYABLE,
            error_reason="temporary_error",
        )
    )

    response = await handle_score_submit(mock_request, service)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.body == b"error: yes"


@pytest.mark.asyncio
async def test_handle_score_submit_parsing_error(valid_multipart_body: bytes) -> None:
    """Test parsing error returns terminal reject."""
    service = StubScoreSubmissionService(
        SubmissionResult(outcome=SubmissionOutcome.COMPLETED, score_id=1)
    )

    request = StubRequest(valid_multipart_body, "text/plain")

    response = await handle_score_submit(request, service)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.body == b"error: no"
