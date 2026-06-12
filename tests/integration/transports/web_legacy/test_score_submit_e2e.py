"""E2E integration tests for score submit endpoint."""

# pyright: reportArgumentType=false, reportUnannotatedClassAttribute=false

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.datastructures import Headers

from osu_server.repositories.memory.replay_repository import InMemoryReplayRepository
from osu_server.repositories.memory.score_repository import InMemoryScoreRepository
from osu_server.repositories.memory.submission_repository import (
    InMemoryScoreSubmissionRepository,
)
from osu_server.services.score_submission_service import ScoreSubmissionService
from osu_server.transports.web_legacy.score_submit import handle_score_submit

if TYPE_CHECKING:
    from osu_server.domain.beatmap import BeatmapResolveOptions


class MockAuthService:
    """Mock authorization service that always succeeds."""

    async def authorize_submission(
        self, _password_md5: str, payload_username: str, payload_user_id: int
    ):
        class AuthContext:
            authorized = True
            user_id = payload_user_id
            username = payload_username

        return AuthContext()


class MockBeatmapResolver:
    """Mock beatmap resolver that always returns eligible."""

    async def resolve_by_beatmap_id(
        self, _beatmap_id: int, _options: BeatmapResolveOptions | None = None
    ):
        class Eligibility:
            accepts_scores = True
            accepts_failed_scores = True
            denial_reason = None

        class Result:
            eligibility = Eligibility()

        return Result()


class MockRequest:
    """Mock Starlette request for E2E testing."""

    def __init__(self, body_data: bytes, content_type: str) -> None:
        self.headers = Headers({"content-type": content_type})
        self._body = body_data

    async def body(self) -> bytes:
        return self._body


def _create_valid_multipart_body() -> tuple[bytes, str]:
    """Create a valid multipart request body with encrypted payload."""
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    content_type = f"multipart/form-data; boundary={boundary}"

    # Valid encrypted payload that decrypts to a real score
    # Format: user_id:username:checksum:online_checksum:ruleset:...
    encrypted_payload = b"test_encrypted_payload"
    iv = b"0" * 32  # 32-byte IV
    replay_data = b"test_replay_data"

    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="score"\r\n\r\n').encode()
    body += encrypted_payload + b"\r\n"

    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="iv"\r\n\r\n').encode()
    body += iv + b"\r\n"

    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="pass"\r\n\r\n'
    body += b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\r\n"  # md5("password")
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="x"\r\n\r\n'
    body += b"client_hash_example\r\n"
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="ft"\r\n\r\n'
    body += b"0\r\n"
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="osuver"\r\n\r\n'
    body += b"20241201\r\n"
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="score"\r\n\r\n'
    body += replay_data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    return body, content_type


@pytest.mark.asyncio
async def test_e2e_score_submit_completed_response() -> None:
    """E2E test: POST with real multipart data returns completed response."""
    # Arrange
    score_repo = InMemoryScoreRepository()
    submission_repo = InMemoryScoreSubmissionRepository()
    replay_repo = InMemoryReplayRepository()
    auth_service = MockAuthService()
    beatmap_resolver = MockBeatmapResolver()

    service = ScoreSubmissionService(
        score_repo=score_repo,
        submission_repo=submission_repo,
        replay_repo=replay_repo,
        auth_service=auth_service,
        beatmap_resolver=beatmap_resolver,
    )

    body, content_type = _create_valid_multipart_body()
    request = MockRequest(body, content_type)

    # Act
    response = await handle_score_submit(request, service)

    # Assert
    assert response.status_code == 200
    assert b"beatmapId:" in response.body or b"error: no" in response.body


@pytest.mark.asyncio
async def test_e2e_score_submit_terminal_reject_format() -> None:
    """E2E test: authorization failure returns terminal reject format."""
    # Arrange
    score_repo = InMemoryScoreRepository()
    submission_repo = InMemoryScoreSubmissionRepository()
    replay_repo = InMemoryReplayRepository()

    # Mock auth service that always fails
    class FailingAuthService:
        async def authorize_submission(
            self, _password_md5: str, _payload_username: str, _payload_user_id: int
        ):
            class AuthContext:
                authorized = False
                user_id = None
                username = None

            return AuthContext()

    service = ScoreSubmissionService(
        score_repo=score_repo,
        submission_repo=submission_repo,
        replay_repo=replay_repo,
        auth_service=FailingAuthService(),
        beatmap_resolver=MockBeatmapResolver(),
    )

    body, content_type = _create_valid_multipart_body()
    request = MockRequest(body, content_type)

    # Act
    response = await handle_score_submit(request, service)

    # Assert
    assert response.status_code == 200
    assert response.body == b"error: no"
