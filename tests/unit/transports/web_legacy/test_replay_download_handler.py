"""Replay download handler auth mapping and orchestration tests."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, cast, final

import pytest

from osu_server.domain.compatibility.stable import (
    ReplayDownloadBranch,
    ReplayDownloadResponseBody,
)
from osu_server.domain.identity.authentication import LegacyWebAuthFailure, LegacyWebAuthResult
from osu_server.domain.scores.score import Ruleset
from osu_server.services.queries.identity import (
    SessionCredentialsQueryInput,
    SessionCredentialsQueryResult,
)
from osu_server.services.queries.scores import (
    ReplayDownloadAccountingMetadata,
    ReplayDownloadQueryInput,
    ReplayDownloadQueryResult,
)
from osu_server.transports.stable.web_legacy.mappers import (
    ReplayDownloadMalformedReason,
    ReplayDownloadParseResult,
    ReplayDownloadRequest,
)
from osu_server.transports.stable.web_legacy.replay_download import ReplayDownloadHandler
from tests.support.starlette_requests import make_starlette_request

if TYPE_CHECKING:
    from collections.abc import Mapping

    from starlette.requests import Request
    from starlette.responses import Response

    from osu_server.services.queries.identity import SessionCredentialsQuery
    from osu_server.services.queries.scores import ReplayDownloadQuery
    from osu_server.transports.stable.web_legacy.mappers import ReplayDownloadQueryParser


_RAW_USERNAME = "SYNTHETIC_RAW_REPLAY_DOWNLOAD_USERNAME"
_RAW_PASSWORD_HASH = "SYNTHETIC_RAW_REPLAY_DOWNLOAD_HASH"
_RAW_SCORE_ID = "SYNTHETIC_RAW_REPLAY_DOWNLOAD_SCORE_ID"
_RAW_MODE = "SYNTHETIC_RAW_REPLAY_DOWNLOAD_MODE"
_SUCCESS_BODY = b"SYNTHETIC_SUCCESS_REPLAY_DOWNLOAD_BODY"


@final
class _AuthQuery:
    def __init__(self, result: LegacyWebAuthResult) -> None:
        self.result = result
        self.inputs: list[SessionCredentialsQueryInput] = []

    async def execute(
        self,
        input_data: SessionCredentialsQueryInput,
    ) -> SessionCredentialsQueryResult:
        self.inputs.append(input_data)
        return SessionCredentialsQueryResult(outcome=self.result)


@final
class _RecordingReplayDownloadQueryParser:
    def __init__(self, result: ReplayDownloadParseResult) -> None:
        self.result = result
        self.call_count = 0

    def parse(self, query: Mapping[str, str]) -> ReplayDownloadParseResult:
        _ = query
        self.call_count += 1
        return self.result


@final
class _ReplayDownloadQuery:
    def __init__(self, result: ReplayDownloadQueryResult) -> None:
        self.result = result
        self.inputs: list[ReplayDownloadQueryInput] = []

    async def execute(
        self,
        input_data: ReplayDownloadQueryInput,
    ) -> ReplayDownloadQueryResult:
        self.inputs.append(input_data)
        return self.result


async def test_auth_failure_returns_empty_401_without_parse_or_query() -> None:
    auth_query = _AuthQuery(
        LegacyWebAuthResult(failure=LegacyWebAuthFailure.INVALID_CREDENTIALS),
    )
    parser = _RecordingReplayDownloadQueryParser(_valid_parse_result())
    replay_query = _ReplayDownloadQuery(_hidden_score_result())
    handler = _make_handler(
        auth_query=auth_query,
        parser=parser,
        replay_query=replay_query,
    )
    query = _query()

    response = await handler(_request(query))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.body == b""
    assert len(response.body) == 0
    assert "content-type" not in response.headers
    assert "content-disposition" not in response.headers
    assert auth_query.inputs == [
        SessionCredentialsQueryInput(
            username=_RAW_USERNAME,
            password_md5=_RAW_PASSWORD_HASH,
        )
    ]
    assert parser.call_count == 0
    assert replay_query.inputs == []
    _assert_response_excludes_raw_inputs(response, query)


async def test_auth_success_shape_without_user_id_returns_empty_401_without_parse_or_query() -> (
    None
):
    auth_query = _AuthQuery(LegacyWebAuthResult(username="PlayerOne"))
    parser = _RecordingReplayDownloadQueryParser(_valid_parse_result())
    replay_query = _ReplayDownloadQuery(_hidden_score_result())
    handler = _make_handler(
        auth_query=auth_query,
        parser=parser,
        replay_query=replay_query,
    )
    query = _query()

    response = await handler(_request(query))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.body == b""
    assert parser.call_count == 0
    assert replay_query.inputs == []
    _assert_response_excludes_raw_inputs(response, query)


async def test_auth_success_calls_parser_and_malformed_request_returns_empty_404() -> None:
    auth_query = _AuthQuery(LegacyWebAuthResult(user_id=42, username="PlayerOne"))
    parser = _RecordingReplayDownloadQueryParser(_malformed_parse_result())
    replay_query = _ReplayDownloadQuery(_hidden_score_result())
    handler = _make_handler(
        auth_query=auth_query,
        parser=parser,
        replay_query=replay_query,
    )
    query = _query()

    response = await handler(_request(query))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.body == b""
    assert len(response.body) == 0
    assert "content-type" not in response.headers
    assert "content-disposition" not in response.headers
    assert parser.call_count == 1
    assert replay_query.inputs == []
    _assert_response_excludes_raw_inputs(
        response,
        query,
        extra_values=(
            ReplayDownloadBranch.MALFORMED_REQUEST_PROVISIONAL.value,
            ReplayDownloadMalformedReason.MISSING_SCORE_ID.value,
        ),
    )


async def test_valid_request_calls_query_with_authenticated_user_and_parsed_values() -> None:
    auth_query = _AuthQuery(LegacyWebAuthResult(user_id=42, username="PlayerOne"))
    parser = _RecordingReplayDownloadQueryParser(_valid_parse_result())
    replay_query = _ReplayDownloadQuery(_hidden_score_result())
    handler = _make_handler(
        auth_query=auth_query,
        parser=parser,
        replay_query=replay_query,
    )
    query = _query()

    response = await handler(_request(query))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.body == b""
    assert len(response.body) == 0
    assert "content-type" not in response.headers
    assert "content-disposition" not in response.headers
    assert replay_query.inputs == [
        ReplayDownloadQueryInput(
            authenticated_user_id=42,
            score_id=8675309,
            ruleset=Ruleset.MANIA,
        )
    ]
    _assert_response_excludes_raw_inputs(
        response,
        query,
        extra_values=(ReplayDownloadBranch.HIDDEN_SCORE.value,),
    )


@pytest.mark.parametrize(
    "branch",
    [
        ReplayDownloadBranch.HIDDEN_SCORE,
        ReplayDownloadBranch.STORAGE_MISSING,
        ReplayDownloadBranch.MISSING_REPLAY_PROVISIONAL,
        ReplayDownloadBranch.BODY_STRATEGY_BLOCKED,
    ],
)
async def test_unavailable_query_result_returns_empty_404_without_branch_leak(
    branch: ReplayDownloadBranch,
) -> None:
    auth_query = _AuthQuery(LegacyWebAuthResult(user_id=42, username="PlayerOne"))
    parser = _RecordingReplayDownloadQueryParser(_valid_parse_result())
    replay_query = _ReplayDownloadQuery(ReplayDownloadQueryResult(branch=branch))
    handler = _make_handler(
        auth_query=auth_query,
        parser=parser,
        replay_query=replay_query,
    )
    query = _query()

    response = await handler(_request(query))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.body == b""
    assert len(response.body) == 0
    assert "content-type" not in response.headers
    assert "content-disposition" not in response.headers
    _assert_response_excludes_raw_inputs(response, query, extra_values=(branch.value,))


async def test_success_query_result_returns_response_body() -> None:
    auth_query = _AuthQuery(LegacyWebAuthResult(user_id=42, username="PlayerOne"))
    parser = _RecordingReplayDownloadQueryParser(_valid_parse_result())
    replay_query = _ReplayDownloadQuery(
        ReplayDownloadQueryResult(
            branch=ReplayDownloadBranch.SUCCESS,
            response_body=ReplayDownloadResponseBody(payload=_SUCCESS_BODY),
            accounting_metadata=ReplayDownloadAccountingMetadata(
                score_id=515,
                score_owner_user_id=616,
            ),
        )
    )
    handler = _make_handler(
        auth_query=auth_query,
        parser=parser,
        replay_query=replay_query,
    )
    query = _query()

    response = await handler(_request(query))

    assert response.status_code == HTTPStatus.OK
    assert response.body == _SUCCESS_BODY
    assert len(response.body) == len(_SUCCESS_BODY)
    assert response.headers["content-type"] == "zip"
    assert response.headers["content-disposition"] == 'attachment; filename="replay.osr"'
    _assert_response_excludes_raw_inputs(response, query, extra_values=("515", "616"))


async def test_unhandled_query_result_branch_fails_loudly() -> None:
    auth_query = _AuthQuery(LegacyWebAuthResult(user_id=42, username="PlayerOne"))
    parser = _RecordingReplayDownloadQueryParser(_valid_parse_result())
    replay_query = _ReplayDownloadQuery(
        ReplayDownloadQueryResult(
            branch=cast(
                "ReplayDownloadBranch",
                cast("object", "synthetic-unhandled-branch"),
            ),
        )
    )
    handler = _make_handler(
        auth_query=auth_query,
        parser=parser,
        replay_query=replay_query,
    )

    with pytest.raises(AssertionError, match="unhandled replay download branch"):
        _ = await handler(_request(_query()))


def _make_handler(
    *,
    auth_query: _AuthQuery,
    parser: _RecordingReplayDownloadQueryParser,
    replay_query: _ReplayDownloadQuery,
) -> ReplayDownloadHandler:
    return ReplayDownloadHandler(
        auth_query=cast("SessionCredentialsQuery", auth_query),
        replay_download_parser=cast("ReplayDownloadQueryParser", cast("object", parser)),
        replay_download_query=cast("ReplayDownloadQuery", cast("object", replay_query)),
    )


def _request(params: Mapping[str, str]) -> Request:
    return make_starlette_request(
        method="GET",
        path="/web/osu-getreplay.php",
        query_params=params,
    )


def _query() -> dict[str, str]:
    return {
        "c": _RAW_SCORE_ID,
        "m": _RAW_MODE,
        "u": _RAW_USERNAME,
        "h": _RAW_PASSWORD_HASH,
    }


def _valid_parse_result() -> ReplayDownloadParseResult:
    return ReplayDownloadParseResult(
        request=ReplayDownloadRequest(score_id=8675309, ruleset=Ruleset.MANIA),
    )


def _malformed_parse_result() -> ReplayDownloadParseResult:
    return ReplayDownloadParseResult(
        branch=ReplayDownloadBranch.MALFORMED_REQUEST_PROVISIONAL,
        reason=ReplayDownloadMalformedReason.MISSING_SCORE_ID,
    )


def _hidden_score_result() -> ReplayDownloadQueryResult:
    return ReplayDownloadQueryResult(branch=ReplayDownloadBranch.HIDDEN_SCORE)


def _assert_response_excludes_raw_inputs(
    response: Response,
    query: Mapping[str, str],
    *,
    extra_values: tuple[str, ...] = (),
) -> None:
    body = bytes(response.body)
    header_block = "\n".join(
        f"{header_name}: {header_value}" for header_name, header_value in response.headers.items()
    ).encode()
    for raw_value in (*query.values(), *extra_values):
        raw_value_bytes = raw_value.encode()
        if raw_value_bytes in body:
            raise AssertionError("response body rendered a raw replay download query value")
        if raw_value_bytes in header_block:
            raise AssertionError("response header rendered a raw replay download query value")
