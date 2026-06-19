"""Stable score submit PP response integration scenarios."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, final

import pytest
from tests.support.fakes import (
    StubBlobStorageService,
    StubScorePayloadDecryptor,
    make_score_authorization_service,
    make_submit_score_use_case,
)
from tests.support.starlette_requests import make_starlette_request

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
from osu_server.services.commands.scores.performance import (
    RequestPerformanceCalculationCommand,
    RequestPerformanceCalculationOutcome,
    RequestPerformanceCalculationResult,
)
from osu_server.services.queries.scores import (
    PerformanceSubmitResponse,
    PerformanceSubmitResponseQuery,
    PerformanceSubmitResponseState,
)
from osu_server.transports.stable.web_legacy.mappers import StableScorePayloadParser
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

if TYPE_CHECKING:
    from starlette.requests import Request

    from osu_server.domain.beatmaps import BeatmapResolveOptions

_BEATMAP_CHECKSUM = "0123456789abcdef0123456789abcdef"
_SUBMITTED_AT = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)


@dataclass(slots=True)
class _BeatmapResolver:
    rank_status: BeatmapRankStatus

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        _ = options
        return _resolve_result(beatmap_id=beatmap_id, rank_status=self.rank_status)

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        _ = options
        assert checksum_md5 == _BEATMAP_CHECKSUM
        return _resolve_result(beatmap_id=1, rank_status=self.rank_status)


@final
class _PerformanceCalculationRequest:
    def __init__(self) -> None:
        self.commands: list[RequestPerformanceCalculationCommand] = []

    async def execute(
        self,
        command: RequestPerformanceCalculationCommand,
    ) -> RequestPerformanceCalculationResult:
        self.commands.append(command)
        return RequestPerformanceCalculationResult(
            outcome=RequestPerformanceCalculationOutcome.CREATED,
            score_id=command.score_id,
            created=True,
        )


@final
class _PerformanceResponses:
    def __init__(self, *responses: PerformanceSubmitResponse) -> None:
        self._responses: tuple[PerformanceSubmitResponse, ...] = responses
        self.queries: list[PerformanceSubmitResponseQuery] = []

    async def wait_for_submit_response(
        self,
        query: PerformanceSubmitResponseQuery,
    ) -> PerformanceSubmitResponse:
        response_index = min(len(self.queries), len(self._responses) - 1)
        self.queries.append(query)
        return self._responses[response_index]

    async def get_submit_response(
        self,
        query: PerformanceSubmitResponseQuery,
    ) -> PerformanceSubmitResponse:
        response_index = min(len(self.queries), len(self._responses) - 1)
        self.queries.append(query)
        return self._responses[response_index]


@final
class _CalculatorIdentity:
    def calculator_name(self) -> str:
        return "test-calculator"

    def calculator_version(self) -> str:
        return "1.2.3"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rank_status",
    [BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED],
)
async def test_ranked_or_approved_submit_returns_pp_when_performance_completes(
    rank_status: BeatmapRankStatus,
) -> None:
    performance_request = _PerformanceCalculationRequest()
    performance_response = _PerformanceResponses(
        PerformanceSubmitResponse(
            state=PerformanceSubmitResponseState.COMPLETED,
            stable_pp=248,
        )
    )
    handler, body, content_type, uow_factory = _make_handler(
        rank_status=rank_status,
        online_checksum=f"online_{rank_status.value}",
        performance_request=performance_request,
        performance_response=performance_response,
    )

    response = await handler(_request(body, content_type))

    assert response.status_code == 200
    assert b"ppAfter:248" in bytes(response.body)
    assert b"rankedScoreAfter:500000" in bytes(response.body)
    assert b"maxComboAfter:99" in bytes(response.body)
    assert len(uow_factory.snapshot().scores_by_id) == 1
    assert len(performance_request.commands) == 1
    assert performance_response.queries == [
        PerformanceSubmitResponseQuery(score_id=1),
    ]


@pytest.mark.asyncio
async def test_pending_submit_returns_retryable_then_same_fingerprint_retry_returns_pp() -> None:
    performance_request = _PerformanceCalculationRequest()
    performance_response = _PerformanceResponses(
        PerformanceSubmitResponse(
            state=PerformanceSubmitResponseState.RETRYABLE,
            stable_pp=None,
        ),
        PerformanceSubmitResponse(
            state=PerformanceSubmitResponseState.COMPLETED,
            stable_pp=312,
        ),
    )
    handler, body, content_type, uow_factory = _make_handler(
        online_checksum="online_retry_after_pending",
        performance_request=performance_request,
        performance_response=performance_response,
    )
    first = await handler(_request(body, content_type))
    second = await handler(_request(body, content_type))

    assert first.body == b"error: yes"
    assert second.status_code == 200
    assert b"ppAfter:312" in bytes(second.body)
    assert len(uow_factory.snapshot().scores_by_id) == 1
    assert len(performance_request.commands) == 1
    assert performance_response.queries == [
        PerformanceSubmitResponseQuery(score_id=1),
        PerformanceSubmitResponseQuery(score_id=1),
    ]


@pytest.mark.asyncio
async def test_unavailable_performance_returns_accepted_response_with_zero_pp() -> None:
    performance_response = _PerformanceResponses(
        PerformanceSubmitResponse(
            state=PerformanceSubmitResponseState.ACCEPTED_WITHOUT_PP,
            stable_pp=0,
        )
    )
    handler, body, content_type, _uow_factory = _make_handler(
        online_checksum="online_unavailable_pp",
        performance_response=performance_response,
    )

    response = await handler(_request(body, content_type))

    assert response.status_code == 200
    response_body = bytes(response.body)
    assert b"ppAfter:0" in response_body
    assert b"unavailable" not in response_body
    assert b"calculator" not in response_body


def _make_handler(
    *,
    online_checksum: str,
    rank_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    performance_request: _PerformanceCalculationRequest | None = None,
    performance_response: _PerformanceResponses,
) -> tuple[ScoreSubmitHandler, bytes, str, InMemoryUnitOfWorkFactory]:
    uow_factory = InMemoryUnitOfWorkFactory()
    payload_decryptor = StubScorePayloadDecryptor(
        DecryptedPayload(
            plaintext=_stable_payload(online_checksum),
            checksum_valid=True,
        )
    )
    service = ProcessScoreSubmissionUseCase(
        submit_score_use_case=make_submit_score_use_case(uow_factory),
        replay_blob_storage=StubBlobStorageService(),
        payload_decryptor=payload_decryptor,
        payload_parser=StableScorePayloadParser(),
        auth_service=make_score_authorization_service(),
        beatmap_resolver=_BeatmapResolver(rank_status),
        performance_calculation_request=performance_request or _PerformanceCalculationRequest(),
        performance_calculator_identity=_CalculatorIdentity(),
        performance_response_query=performance_response,
    )
    body, content_type = _multipart_body()
    return ScoreSubmitHandler(service), body, content_type, uow_factory


def _multipart_body() -> tuple[bytes, str]:
    boundary = "----AthenaScoreSubmitBoundary"
    content_type = f"multipart/form-data; boundary={boundary}"
    encrypted_payload = base64.b64encode(b"stable-submit-performance")
    iv = base64.b64encode(b"0" * 32)
    replay_data = b"stable-submit-performance-replay"

    body = b"".join(
        (
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="score"\r\n\r\n',
            encrypted_payload,
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="iv"\r\n\r\n',
            iv,
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="pass"\r\n\r\n',
            b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="x"\r\n\r\n',
            b"client_hash_performance\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="ft"\r\n\r\n',
            b"0\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="osuver"\r\n\r\n',
            b"20241201\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="score"\r\n\r\n',
            replay_data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        )
    )
    return body, content_type


def _request(body: bytes, content_type: str) -> Request:
    return make_starlette_request(
        method="POST",
        path="/web/osu-submit-modular-selector.php",
        headers=((b"content-type", content_type.encode()),),
        body=body,
    )


def _stable_payload(online_checksum: str) -> str:
    return (
        f"{_BEATMAP_CHECKSUM}:test_user:{online_checksum}:"
        "300:50:0:10:5:0:500000:99:1:A:0:1:0:260616120000:20241201:client"
    )


def _resolve_result(
    *,
    beatmap_id: int,
    rank_status: BeatmapRankStatus,
) -> BeatmapResolveResult:
    beatmap = Beatmap(
        id=beatmap_id,
        beatmapset_id=10,
        checksum_md5=_BEATMAP_CHECKSUM,
        mode="osu",
        version="Performance Test",
        total_length=None,
        hit_length=None,
        max_combo=None,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=rank_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_SUBMITTED_AT,
        next_refresh_at=None,
    )
    return BeatmapResolveResult(
        beatmap=beatmap,
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
        last_fetched_at=_SUBMITTED_AT,
        next_refresh_at=None,
        reason=None,
    )
