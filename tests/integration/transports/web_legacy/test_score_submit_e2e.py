"""E2E integration tests for score submit endpoint."""

# pyright: reportArgumentType=false, reportUnannotatedClassAttribute=false

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import pytest
from starlette.datastructures import Headers
from tests.support.fakes import (
    StubBlobStorageService,
    StubScorePayloadDecryptor,
    make_submit_score_use_case,
)

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapResolveResult,
    BeatmapSourceVerification,
)
from osu_server.domain.scores.decryption import DecryptedPayload
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores import ProcessScoreSubmissionUseCase
from osu_server.services.score_authorization_service import AuthorizationContext
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import BeatmapResolveOptions


def _resolved_beatmap() -> Beatmap:
    return Beatmap(
        id=1,
        beatmapset_id=10,
        checksum_md5="0123456789abcdef0123456789abcdef",
        mode="osu",
        version="Test",
        total_length=None,
        hit_length=None,
        max_combo=None,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=None,
        next_refresh_at=None,
    )


def _eligible_result() -> BeatmapResolveResult:
    return BeatmapResolveResult(
        beatmap=_resolved_beatmap(),
        beatmapset=None,
        eligibility=BeatmapEligibility(
            accepts_scores=True,
            has_leaderboard=True,
            awards_ranked_pp=True,
            awards_loved_pp=False,
            requires_osu_file_for_pp=True,
            is_officially_verified=True,
            is_mirror_derived=False,
            accepts_failed_scores=True,
            failed_scores_have_leaderboard=False,
            failed_scores_update_best_score=False,
            failed_scores_award_ranked_pp=False,
            failed_scores_award_loved_pp=False,
            denial_reason=None,
        ),
        metadata_status=BeatmapFetchState.FRESH,
        file_status=BeatmapFileState.MISSING,
        source=BeatmapMetadataSource.OFFICIAL,
        verified=True,
        last_fetched_at=None,
        next_refresh_at=None,
        reason=None,
    )


class MockAuthService:
    """Mock authorization service that always succeeds."""

    async def authorize_submission(
        self, _password_md5: str, payload_username: str, payload_user_id: int
    ) -> AuthorizationContext:
        return AuthorizationContext(
            user_id=payload_user_id,
            username=payload_username,
            session_valid=True,
            password_valid=True,
            payload_identity_match=True,
        )


class MockBeatmapResolver:
    """Mock beatmap resolver that always returns eligible."""

    async def resolve_by_beatmap_id(
        self, _beatmap_id: int, _options: BeatmapResolveOptions | None = None
    ) -> BeatmapResolveResult:
        return _eligible_result()

    async def resolve_by_checksum(
        self, _checksum_md5: str, _options: BeatmapResolveOptions | None = None
    ) -> BeatmapResolveResult:
        return _eligible_result()


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
    encrypted_payload = base64.b64encode(b"test_encrypted_payload")
    iv = base64.b64encode(b"0" * 32)
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


def _score_payload_decryptor() -> StubScorePayloadDecryptor:
    return StubScorePayloadDecryptor(
        DecryptedPayload(
            plaintext="1000:test_user:abc123:e2e_score_submit:0:0:100:10:5:0:0:2:500000:99:1:1",
            checksum_valid=True,
        )
    )


def _make_process_score_submission_use_case(
    *, auth_service: object
) -> ProcessScoreSubmissionUseCase:
    uow_factory = InMemoryUnitOfWorkFactory()
    return ProcessScoreSubmissionUseCase(
        submit_score_use_case=make_submit_score_use_case(uow_factory),
        replay_blob_storage=StubBlobStorageService(),
        payload_decryptor=_score_payload_decryptor(),
        auth_service=auth_service,
        beatmap_resolver=MockBeatmapResolver(),
    )


@pytest.mark.asyncio
async def test_e2e_score_submit_completed_response() -> None:
    """E2E test: POST with real multipart data returns completed response."""
    # Arrange
    auth_service = MockAuthService()

    service = _make_process_score_submission_use_case(auth_service=auth_service)
    handler = ScoreSubmitHandler(service)

    body, content_type = _create_valid_multipart_body()
    request = MockRequest(body, content_type)

    # Act
    response = await handler(request)

    # Assert
    assert response.status_code == 200
    response_body = bytes(response.body)
    assert response_body.startswith(b"1:0:1:3\n")
    assert b"chartId:overall\n" in response_body


@pytest.mark.asyncio
async def test_e2e_score_submit_terminal_reject_format() -> None:
    """E2E test: authorization failure returns terminal reject format."""

    # Arrange
    # Mock auth service that always fails
    class FailingAuthService:
        async def authorize_submission(
            self, _password_md5: str, _payload_username: str, _payload_user_id: int
        ) -> AuthorizationContext:
            return AuthorizationContext(
                user_id=0,
                username="",
                session_valid=False,
                password_valid=False,
                payload_identity_match=False,
            )

    service = _make_process_score_submission_use_case(auth_service=FailingAuthService())
    handler = ScoreSubmitHandler(service)

    body, content_type = _create_valid_multipart_body()
    request = MockRequest(body, content_type)

    # Act
    response = await handler(request)

    # Assert
    assert response.status_code == 200
    assert response.body == b"error: no"
