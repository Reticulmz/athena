"""E2E integration tests for score submit endpoint."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, cast

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
from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.mods import Mod
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserProjectionSlice,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores import (
    ProcessScoreSubmissionUseCase,
    ScoreSubmissionAuthorizer,
)
from osu_server.services.commands.scores.authorization import AuthorizationContext
from osu_server.transports.stable.web_legacy.mappers import (
    StableScorePayloadParser,
    StableScoreSubmitMapper,
)
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

if TYPE_CHECKING:
    from starlette.requests import Request

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
        self, password_md5: str, payload_username: str, payload_user_id: int
    ) -> AuthorizationContext:
        _ = password_md5
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
        self, beatmap_id: int, options: BeatmapResolveOptions | None = None
    ) -> BeatmapResolveResult:
        _ = beatmap_id, options
        return _eligible_result()

    async def resolve_by_checksum(
        self, checksum_md5: str, options: BeatmapResolveOptions | None = None
    ) -> BeatmapResolveResult:
        _ = checksum_md5, options
        return _eligible_result()


class MockRequest:
    """Mock Starlette request for E2E testing."""

    headers: Headers
    _body: bytes

    def __init__(self, body_data: bytes, content_type: str) -> None:
        self.headers = Headers({"content-type": content_type})
        self._body = body_data

    async def body(self) -> bytes:
        return self._body


def _request(body_data: bytes, content_type: str) -> Request:
    return cast("Request", cast("object", MockRequest(body_data, content_type)))


def _create_valid_multipart_body(
    *,
    encrypted_payload: bytes = b"test_encrypted_payload",
    replay_data: bytes = b"test_replay_data",
    client_hash: bytes = b"client_hash_example",
) -> tuple[bytes, str]:
    """Create a valid multipart request body with encrypted payload."""
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    content_type = f"multipart/form-data; boundary={boundary}"

    # Valid encrypted payload that decrypts to a real score
    # Format: user_id:username:checksum:online_checksum:ruleset:...
    encrypted_payload = base64.b64encode(encrypted_payload)
    iv = base64.b64encode(b"0" * 32)

    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="score"\r\n\r\n').encode()
    body += encrypted_payload + b"\r\n"

    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="iv"\r\n\r\n').encode()
    body += iv + b"\r\n"

    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="pass"\r\n\r\n'
    body += b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\r\n"  # md5("password")
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="x"\r\n\r\n'
    body += client_hash + b"\r\n"
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
    *, auth_service: ScoreSubmissionAuthorizer
) -> ProcessScoreSubmissionUseCase:
    uow_factory = InMemoryUnitOfWorkFactory()
    return ProcessScoreSubmissionUseCase(
        submit_score_use_case=make_submit_score_use_case(uow_factory),
        replay_blob_storage=StubBlobStorageService(),
        payload_decryptor=_score_payload_decryptor(),
        payload_parser=StableScorePayloadParser(),
        auth_service=auth_service,
        beatmap_resolver=MockBeatmapResolver(),
    )


def _leaderboard_scope(mod_filter_key: int | None = None) -> BeatmapLeaderboardUserBestScope:
    return BeatmapLeaderboardUserBestScope(
        beatmap_id=1,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        user_id=1000,
        mod_filter_key=mod_filter_key,
    )


async def _get_leaderboard_best_score_id(
    uow_factory: InMemoryUnitOfWorkFactory,
    *,
    mod_filter_key: int | None = None,
) -> int | None:
    async with uow_factory() as uow:
        best = await uow.beatmap_leaderboards.get_user_best(_leaderboard_scope(mod_filter_key))
        return best.score_id if best is not None else None


async def _replace_projection_with_score(
    uow_factory: InMemoryUnitOfWorkFactory,
    *,
    score_id: int,
) -> None:
    async with uow_factory() as uow:
        score = await uow.scores.get_by_id(score_id)
        assert score is not None
        await uow.beatmap_leaderboards.replace_projection_slice(
            BeatmapLeaderboardUserProjectionSlice(user_id=1000),
            (
                UpsertBeatmapLeaderboardUserBest(
                    scope=_leaderboard_scope(),
                    score_id=score_id,
                    rank_key=ScoreRankKey(
                        score=score.score,
                        submitted_at=score.submitted_at,
                        score_id=score_id,
                    ),
                ),
            ),
        )
        await uow.commit()


@pytest.mark.asyncio
async def test_e2e_score_submit_completed_response() -> None:
    """E2E test: POST with real multipart data returns completed response."""
    # Arrange
    auth_service = MockAuthService()

    service = _make_process_score_submission_use_case(auth_service=auth_service)
    handler = ScoreSubmitHandler(
        service,
        mapper=StableScoreSubmitMapper(stable_web_base_url="https://osu.athena.localhost"),
    )

    body, content_type = _create_valid_multipart_body()
    request = _request(body, content_type)

    # Act
    response = await handler(request)

    # Assert
    assert response.status_code == 200
    response_body = bytes(response.body)
    assert response_body.startswith(
        b"beatmapId:1|beatmapSetId:0|beatmapPlaycount:1|beatmapPasscount:1|approvedDate:\n"
    )
    assert (
        b"chartId:beatmap|chartUrl:https://osu.athena.localhost/b/1|chartName:Beatmap Ranking|"
    ) in response_body
    assert (
        b"chartId:overall|chartUrl:https://osu.athena.localhost/u/1000|chartName:Overall Ranking|"
    ) in response_body


@pytest.mark.asyncio
async def test_e2e_score_submit_updates_projection_and_retry_returns_saved_snapshot() -> None:
    """Stable submit updates projection and same request retry does not recalculate."""
    uow_factory = InMemoryUnitOfWorkFactory()

    def decrypt_payload(
        encrypted: bytes,
        _iv: bytes,
        _osu_version: str | None,
    ) -> DecryptedPayload:
        if encrypted == b"previous_best_payload":
            payload = "1000:test_user:abc123:e2e_lb_prev:0:0:100:10:5:0:0:2:400000:99:1:1"
        else:
            payload = (
                "1000:test_user:abc123:e2e_lb_new:0:"
                f"{int(Mod.DOUBLE_TIME)}:100:10:5:0:0:2:500000:99:1:1"
            )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    service = ProcessScoreSubmissionUseCase(
        submit_score_use_case=make_submit_score_use_case(uow_factory),
        replay_blob_storage=StubBlobStorageService(),
        payload_decryptor=StubScorePayloadDecryptor(factory=decrypt_payload),
        payload_parser=StableScorePayloadParser(),
        auth_service=MockAuthService(),
        beatmap_resolver=MockBeatmapResolver(),
    )
    handler = ScoreSubmitHandler(service)

    previous_body, previous_content_type = _create_valid_multipart_body(
        encrypted_payload=b"previous_best_payload",
        replay_data=b"previous_best_replay",
        client_hash=b"previous_hash",
    )
    previous_response = await handler(_request(previous_body, previous_content_type))

    assert previous_response.status_code == 200
    previous_response_body = bytes(previous_response.body)
    assert b"rankedScoreBefore:0|rankedScoreAfter:400000|" in previous_response_body
    previous_best_score_id = await _get_leaderboard_best_score_id(uow_factory)
    assert previous_best_score_id is not None

    new_body, new_content_type = _create_valid_multipart_body(
        encrypted_payload=b"new_best_payload",
        replay_data=b"new_best_replay",
        client_hash=b"new_hash",
    )
    new_response = await handler(_request(new_body, new_content_type))

    assert new_response.status_code == 200
    new_response_body = bytes(new_response.body)
    assert b"rankedScoreBefore:400000|rankedScoreAfter:500000|" in new_response_body
    new_best_score_id = await _get_leaderboard_best_score_id(uow_factory)
    selected_mods_score_id = await _get_leaderboard_best_score_id(
        uow_factory,
        mod_filter_key=int(Mod.DOUBLE_TIME),
    )
    assert new_best_score_id is not None
    assert new_best_score_id != previous_best_score_id
    assert selected_mods_score_id == new_best_score_id

    await _replace_projection_with_score(uow_factory, score_id=previous_best_score_id)

    retry_response = await handler(_request(new_body, new_content_type))

    assert retry_response.status_code == 200
    assert bytes(retry_response.body) == new_response_body
    assert await _get_leaderboard_best_score_id(uow_factory) == previous_best_score_id
    assert (
        await _get_leaderboard_best_score_id(
            uow_factory,
            mod_filter_key=int(Mod.DOUBLE_TIME),
        )
        is None
    )


@pytest.mark.asyncio
async def test_e2e_score_submit_terminal_reject_format() -> None:
    """E2E test: authorization failure returns terminal reject format."""

    # Arrange
    # Mock auth service that always fails
    class FailingAuthService:
        async def authorize_submission(
            self, password_md5: str, payload_username: str, payload_user_id: int
        ) -> AuthorizationContext:
            _ = password_md5, payload_username, payload_user_id
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
    request = _request(body, content_type)

    # Act
    response = await handler(request)

    # Assert
    assert response.status_code == 200
    assert response.body == b"error: no"
