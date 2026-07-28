"""Stable score submit handlerのmultipart, response, stats event contractを検証する."""

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
    StableScoreSubmitMapper,
)
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler
from tests.support.fakes import make_stable_score_submit_decoder
from tests.support.starlette_requests import make_starlette_request


class ProcessScoreSubmissionUseCaseProtocol(Protocol):
    """Score submission command test doubleが満たすexecute interfaceを定義する."""

    async def execute(self, input_data: ParsedSubmissionInput) -> SubmissionResult:
        """Parsed submission inputをcommand resultへ処理する.

        Args:
            input_data (ParsedSubmissionInput): decrypt済みscoreとrequest metadataを持つcommand
                input.

        Returns:
            SubmissionResult: completed, retryable, terminal rejectionのいずれかを持つresult.
        """
        ...


class StubProcessScoreSubmissionUseCase:
    """Handler testのため設定済みscore submission resultを返すstubを提供する.

    Attributes:
        last_input (ParsedSubmissionInput | None): executeへ最後に渡されたcommand input.
    """

    def __init__(self, result: SubmissionResult) -> None:
        """各execute callで返すscore submission resultを設定する.

        Args:
            result (SubmissionResult): testで再現するcommand outcome.
        """
        self._result: SubmissionResult = result
        self.last_input: ParsedSubmissionInput | None = None

    async def execute(self, input_data: ParsedSubmissionInput) -> SubmissionResult:
        """Command inputを記録して設定済みresultを返す.

        Args:
            input_data (ParsedSubmissionInput): handlerがdecoderから取得したcommand input.

        Returns:
            SubmissionResult: constructorで設定したcommand result.
        """
        self.last_input = input_data
        return self._result


@final
class StubCurrentUserStatsQuery:
    """設定済みcurrent user statisticsを返すquery fakeを提供する.

    Attributes:
        inputs (list[CurrentUserStatsQueryInput]): executeへ渡されたstats query inputの順序.
    """

    def __init__(self, stats: tuple[UserCurrentStats, ...]) -> None:
        """返却するcurrent user statisticsを設定する.

        Args:
            stats (tuple[UserCurrentStats, ...]): requested userのcurrent stats tuple.
        """
        self._stats = stats
        self.inputs: list[CurrentUserStatsQueryInput] = []

    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult:
        """Stats query inputを記録して設定済みstatisticsを返す.

        Args:
            input_data (CurrentUserStatsQueryInput): user ID, ruleset, playstyleを持つquery input.

        Returns:
            CurrentUserStatsQueryResult: constructorで設定したcurrent statsを持つresult.
        """
        self.inputs.append(input_data)
        return CurrentUserStatsQueryResult(stats=self._stats)


@final
class StubLocalEventBus:
    """Published eventを記録しsubscriptionを無視するlocal event bus fakeを提供する.

    Attributes:
        events (list[object]): fireされたeventの順序.
    """

    def __init__(self) -> None:
        """Empty published event listを初期化する."""
        self.events: list[object] = []

    async def fire(self, event: object) -> None:
        """Eventをpublished listへ追加する.

        Args:
            event (object): score submit handlerがfireするdomain event.

        Returns:
            None: eventの記録を完了する.
        """
        self.events.append(event)

    def subscribe(self, event_type: type[object], handler: object) -> None:
        """Subscription requestを無視してprotocol compatibilityを保つ.

        Args:
            event_type (type[object]): subscribe対象のevent type.
            handler (object): eventを処理するcallbackまたはhandler object.

        Returns:
            None: fakeがsubscriberを保持しないまま完了する.
        """
        _ = (event_type, handler)


def _score_submit_request(body: bytes, content_type: str) -> Request:
    """Stable score submit endpointへ送るStarlette POST requestを構築する.

    Args:
        body (bytes): multipartまたはinvalid test request body.
        content_type (str): request headerへ設定するcontent type value.

    Returns:
        Request: osu-submit-modular-selector.php pathを持つStarlette request.
    """
    return make_starlette_request(
        method="POST",
        path="/web/osu-submit-modular-selector.php",
        headers=((b"content-type", content_type.encode()),),
        body=body,
    )


@pytest.fixture
def valid_multipart_body() -> bytes:
    """Decoder fakeが処理できるvalid stable multipart request bodyを構築する.

    Returns:
        bytes: score payload, IV, credential, metadata, replayを含むmultipart body.

    Notes:
        encrypted payloadはtest decoderが復号するsynthetic binaryとして扱う.
    """
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
    """Stable score submit handlerへ渡すStarlette requestを構築する.

    Args:
        valid_multipart_body (bytes): valid multipart fixtureが返すrequest body.

    Returns:
        Request: stable score submit endpointへのPOST request.

    Notes:
        TestClientを使わずhandlerに必要なrequest surfaceだけを持つ.
    """
    return _score_submit_request(
        valid_multipart_body, "multipart/form-data; boundary=----WebKitFormBoundary"
    )


@pytest.mark.asyncio
async def test_handle_score_submit_completed(mock_request: Request) -> None:
    """Completed resultをstable chart responseへ変換するcontractを検証する.

    Args:
        mock_request (Request): valid multipart bodyを持つscore submit request.

    Returns:
        None: chart response, opaque token hash, multipart parse logを確認して完了する.

    Raises:
        AssertionError: response bodyまたはcommand input mappingがexpected valueと異なる場合.

    Notes:
        opaque tokenはhash化され生値をcommand inputへ残さない.
    """
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12345,
        )
    )
    handler = ScoreSubmitHandler(service, decoder=make_stable_score_submit_decoder())

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
    """Completed score submissionがcurrent stats chartとeventを生成するcontractを検証する.

    Args:
        mock_request (Request): valid multipart bodyを持つscore submit request.

    Returns:
        None: stats query input, chart field, CurrentUserStatsUpdated eventを確認して完了する.
    """
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
        decoder=make_stable_score_submit_decoder(),
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
    """Command resultのcurrent statsがchartとeventへ直接使われるcontractを検証する.

    Args:
        mock_request (Request): valid multipart bodyを持つscore submit request.

    Returns:
        None: stats queryなしでbefore/after chart fieldとeventが得られることを確認する.
    """
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
        decoder=make_stable_score_submit_decoder(),
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
    """Terminal reject resultをstable reject responseへ変換するcontractを検証する.

    Args:
        mock_request (Request): valid multipart bodyを持つscore submit request.

    Returns:
        None: legacy terminal reject bodyとwarning logを確認して完了する.

    Raises:
        AssertionError: response bodyまたはwarning logがexpected valueと異なる場合.

    Notes:
        command error_reasonはlogへ残すがresponse bodyはlegacy compatibility形式にする.
    """
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(
            outcome=SubmissionOutcome.TERMINAL_REJECTED,
            error_reason="authorization_failure",
        )
    )
    handler = ScoreSubmitHandler(service, decoder=make_stable_score_submit_decoder())

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
    """Retryable resultをstable retry responseへ変換するcontractを検証する.

    Args:
        mock_request (Request): valid multipart bodyを持つscore submit request.

    Returns:
        None: legacy clientが再送するerror: yes bodyを確認して完了する.

    Raises:
        AssertionError: response statusまたはbodyがexpected valueと異なる場合.

    Notes:
        retryable responseはlegacy clientが再送するerror: yesを返す.
    """
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(
            outcome=SubmissionOutcome.RETRYABLE,
            error_reason="temporary_error",
        )
    )
    handler = ScoreSubmitHandler(service, decoder=make_stable_score_submit_decoder())

    response = await handler(mock_request)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.body == b"error: yes"


@pytest.mark.asyncio
async def test_handle_score_submit_parsing_error(valid_multipart_body: bytes) -> None:
    """Multipart parse failureをstable terminal reject responseへ変換するcontractを検証する.

    Args:
        valid_multipart_body (bytes): content type mismatchでparse failureを起こすmultipart body.

    Returns:
        None: commandを呼ばずlegacy terminal reject bodyを返すことを確認して完了する.

    Raises:
        AssertionError: response bodyまたはlog reasonがexpected valueと異なる場合.

    Notes:
        multipart parse failureではcommand use-caseを呼び出さない.
    """
    service = StubProcessScoreSubmissionUseCase(
        SubmissionResult(outcome=SubmissionOutcome.COMPLETED, score_id=1)
    )
    handler = ScoreSubmitHandler(service, decoder=make_stable_score_submit_decoder())

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
