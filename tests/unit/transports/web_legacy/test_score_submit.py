"""Unit tests for score submit handler."""

import base64
import hashlib
from decimal import Decimal
from typing import Protocol, final

import pytest
import structlog.testing
from starlette.requests import Request
from starlette.responses import Response

from osu_server.domain.events.scores import CurrentUserStatsUpdated
from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.domain.scores.decryption import DecryptedPayload
from osu_server.domain.scores.user_stats import UserCurrentStats
from osu_server.services.commands.scores import (
    ParsedSubmissionInput,
    SubmissionOutcome,
    SubmissionResult,
)
from osu_server.services.queries.scores import (
    CurrentUserStatsQueryInput,
    CurrentUserStatsQueryResult,
)
from osu_server.transports.stable.web_legacy.mappers import (
    StableScorePayloadParser,
    StableScoreSubmitDecoder,
    StableScoreSubmitMapper,
)
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler
from tests.support.fakes import StubScorePayloadDecryptor
from tests.support.starlette_requests import make_starlette_request


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


@final
class StubCurrentUserStatsQuery:
    def __init__(self, stats: tuple[UserCurrentStats, ...]) -> None:
        self._stats = stats
        self.inputs: list[CurrentUserStatsQueryInput] = []

    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult:
        self.inputs.append(input_data)
        return CurrentUserStatsQueryResult(stats=self._stats)


@final
class StubLocalEventBus:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def fire(self, event: object) -> None:
        self.events.append(event)

    def subscribe(self, event_type: type[object], handler: object) -> None:
        _ = (event_type, handler)


def _score_submit_request(body: bytes, content_type: str) -> Request:
    return make_starlette_request(
        method="POST",
        path="/web/osu-submit-modular-selector.php",
        headers=((b"content-type", content_type.encode()),),
        body=body,
    )


def _score_submit_decoder() -> StableScoreSubmitDecoder:
    return StableScoreSubmitDecoder(
        payload_decryptor=StubScorePayloadDecryptor(
            DecryptedPayload(
                plaintext="1000:test_user:abc123:online_checksum:0:0:100:10:5:0:0:2:500000:99:1:1",
                checksum_valid=True,
            )
        ),
        payload_parser=StableScorePayloadParser(),
    )


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
def mock_request(valid_multipart_body: bytes) -> Request:
    """Mock Starlette request."""
    return _score_submit_request(
        valid_multipart_body, "multipart/form-data; boundary=----WebKitFormBoundary"
    )


@pytest.mark.asyncio
async def test_handle_score_submit_completed(mock_request: Request) -> None:
    """Test completed response format."""
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12345,
        )
    )
    handler = ScoreSubmitHandler(service, decoder=_score_submit_decoder())

    with structlog.testing.capture_logs() as cap_logs:
        response = await handler(mock_request)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert b":" in response.body
    assert b"chartId:" in response.body
    assert service.last_input is not None
    assert service.last_input.beatmap_id is None
    assert service.last_input.opaque_field_hashes == {
        "token_sha256": hashlib.sha256(b"session_token").hexdigest()
    }
    assert any(
        entry["event"] == "score_submission_multipart_parsed"
        and entry["score_field_count"] == 2
        and entry["replay_present"] is True
        and entry["replay_byte_size"] == len(b"replay_binary_data")
        for entry in cap_logs
    )


@pytest.mark.asyncio
async def test_handle_score_submit_fires_current_user_stats_event(
    mock_request: Request,
) -> None:
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            user_id=20,
            score_id=12345,
            ruleset=Ruleset.MANIA,
            playstyle=Playstyle.VANILLA,
        )
    )
    current_stats = UserCurrentStats(
        user_id=20,
        pp=Decimal("122.5"),
        accuracy=0.9876,
        global_rank=12,
        play_count=34,
        ranked_score=123_456_789,
        total_score=9_876_543_210,
        max_combo=1234,
    )
    stats_query = StubCurrentUserStatsQuery((current_stats,))
    event_bus = StubLocalEventBus()
    handler = ScoreSubmitHandler(
        service,
        decoder=_score_submit_decoder(),
        mapper=StableScoreSubmitMapper(stable_web_base_url="https://osu.athena.localhost"),
        current_user_stats_query=stats_query,
        event_bus=event_bus,
    )

    response = await handler(mock_request)

    assert response.status_code == 200
    response_body = bytes(response.body)
    assert (
        b"chartId:overall|chartUrl:https://osu.athena.localhost/u/20|chartName:Overall Ranking|"
    ) in response_body
    assert b"rankAfter:12" in response_body
    assert b"rankedScoreAfter:123456789" in response_body
    assert b"totalScoreAfter:9876543210" in response_body
    assert b"maxComboAfter:1234" in response_body
    assert b"accuracyAfter:98.76" in response_body
    assert b"ppAfter:123" in response_body
    assert stats_query.inputs == [
        CurrentUserStatsQueryInput(
            user_ids=(20,),
            ruleset=Ruleset.MANIA,
            playstyle=Playstyle.VANILLA,
        )
    ]
    assert event_bus.events == [
        CurrentUserStatsUpdated(
            user_id=20,
            ruleset=Ruleset.MANIA,
            playstyle=Playstyle.VANILLA,
            current_stats=current_stats,
        )
    ]


@pytest.mark.asyncio
async def test_handle_score_submit_uses_result_current_stats_for_response_and_event(
    mock_request: Request,
) -> None:
    overall_stats_after = UserCurrentStats(
        user_id=20,
        pp=Decimal("248.5"),
        accuracy=0.9876,
        global_rank=1,
        play_count=8,
        ranked_score=500_000,
        total_score=1_400_000,
    )
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            user_id=20,
            score_id=12345,
            ruleset=Ruleset.MANIA,
            playstyle=Playstyle.VANILLA,
            overall_stats_before=UserCurrentStats(
                user_id=20,
                pp=Decimal("122.4"),
                accuracy=0.9567,
                global_rank=2,
                play_count=7,
                ranked_score=400_000,
                total_score=900_000,
            ),
            overall_stats_after=overall_stats_after,
        )
    )
    stats_query = StubCurrentUserStatsQuery(())
    event_bus = StubLocalEventBus()
    handler = ScoreSubmitHandler(
        service,
        decoder=_score_submit_decoder(),
        current_user_stats_query=stats_query,
        event_bus=event_bus,
    )

    response = await handler(mock_request)

    assert response.status_code == 200
    response_body = bytes(response.body)
    assert b"rankBefore:2" in response_body
    assert b"rankAfter:1" in response_body
    assert b"rankedScoreBefore:400000" in response_body
    assert b"rankedScoreAfter:500000" in response_body
    assert stats_query.inputs == []
    assert event_bus.events == [
        CurrentUserStatsUpdated(
            user_id=20,
            ruleset=Ruleset.MANIA,
            playstyle=Playstyle.VANILLA,
            current_stats=overall_stats_after,
        )
    ]


@pytest.mark.asyncio
async def test_handle_score_submit_terminal_reject(mock_request: Request) -> None:
    """Test terminal reject response format."""
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(
            outcome=SubmissionOutcome.TERMINAL_REJECTED,
            error_reason="authorization_failure",
        )
    )
    handler = ScoreSubmitHandler(service, decoder=_score_submit_decoder())

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
async def test_handle_score_submit_retryable(mock_request: Request) -> None:
    """Test retryable response format."""
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(
            outcome=SubmissionOutcome.RETRYABLE,
            error_reason="temporary_error",
        )
    )
    handler = ScoreSubmitHandler(service, decoder=_score_submit_decoder())

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
    handler = ScoreSubmitHandler(service, decoder=_score_submit_decoder())

    request = _score_submit_request(valid_multipart_body, "text/plain")

    with structlog.testing.capture_logs() as cap_logs:
        response = await handler(request)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.body == b"error: no"
    assert any(
        entry["event"] == "score_submission_failed" and entry["reason"] == "multipart_parse_failed"
        for entry in cap_logs
    )
