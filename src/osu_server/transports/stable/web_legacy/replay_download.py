"""Stable legacy replay download handler."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from starlette.responses import Response

from osu_server.domain.compatibility.stable import ReplayDownloadBranch
from osu_server.services.queries.identity import SessionCredentialsQueryInput
from osu_server.services.queries.scores import ReplayDownloadQueryInput

if TYPE_CHECKING:
    from collections.abc import Mapping

    from starlette.requests import Request

    from osu_server.services.queries.identity import SessionCredentialsQuery
    from osu_server.services.queries.scores import ReplayDownloadQuery, ReplayDownloadQueryResult
    from osu_server.transports.stable.web_legacy.mappers import ReplayDownloadQueryParser

_SUCCESS_CONTENT_DISPOSITION = 'attachment; filename="replay.osr"'
_SUCCESS_CONTENT_TYPE = "zip"
_EMPTY_NOT_FOUND_BRANCHES = frozenset(
    {
        ReplayDownloadBranch.HIDDEN_SCORE,
        ReplayDownloadBranch.STORAGE_MISSING,
        ReplayDownloadBranch.MISSING_REPLAY_PROVISIONAL,
        ReplayDownloadBranch.MALFORMED_REQUEST_PROVISIONAL,
        ReplayDownloadBranch.BODY_STRATEGY_BLOCKED,
    }
)


class StableReplayDownloadExchange:
    """Stable replay download の auth, parse, query orchestration を行う.

    Args:
        auth_query: Stable legacy credential を検証する query boundary.
        replay_download_parser: Confirmed replay download query keys を parse する mapper.
        replay_download_query: Replay download branch を解決する query use-case.

    Returns:
        Class のため戻り値はない.

    Raises:
        なし.

    Constraints:
        `u` と `h` は auth mapping だけに渡す. Auth failure では parser と
        replay query を呼ばない. Unavailable branch の内部原因は response に
        含めない.
    """

    def __init__(
        self,
        *,
        auth_query: SessionCredentialsQuery,
        replay_download_parser: ReplayDownloadQueryParser,
        replay_download_query: ReplayDownloadQuery,
    ) -> None:
        self._auth_query: SessionCredentialsQuery = auth_query
        self._replay_download_parser: ReplayDownloadQueryParser = replay_download_parser
        self._replay_download_query: ReplayDownloadQuery = replay_download_query

    async def respond(self, query: Mapping[str, str]) -> Response:
        """Stable replay download query を HTTP response に変換する.

        Args:
            query: Starlette QueryParams 互換または plain mapping.

        Returns:
            Auth failure は empty 401. Malformed parse と unavailable branch は
            empty 404. Success branch は target-compatible body と download
            header を返す.

        Raises:
            Query use-case の想定外例外はそのまま送出する.

        Constraints:
            Raw query values, credential values, storage detail は response に含めない.
        """

        auth_query_result = await self._auth_query.execute(
            SessionCredentialsQueryInput(
                username=query.get("u"),
                password_md5=query.get("h"),
            ),
        )
        auth_result = auth_query_result.outcome
        if auth_result.failure is not None:
            return _empty_response(HTTPStatus.UNAUTHORIZED)

        user_id = auth_result.user_id
        assert user_id is not None

        parse_result = self._replay_download_parser.parse(query)
        if parse_result.request is None:
            return _empty_response(HTTPStatus.NOT_FOUND)

        request_obj = parse_result.request
        result = await self._replay_download_query.execute(
            ReplayDownloadQueryInput(
                authenticated_user_id=user_id,
                score_id=request_obj.score_id,
                ruleset=request_obj.ruleset,
            )
        )
        return _response_from_query_result(result)


class ReplayDownloadHandler:
    """Starlette adapter for `GET /web/osu-getreplay.php`.

    Args:
        auth_query: Stable legacy credential を検証する query boundary.
        replay_download_parser: Replay download query parser.
        replay_download_query: Replay download query use-case.

    Returns:
        Class のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Route registration と DI wiring は後続 task が所有する.
    """

    def __init__(
        self,
        *,
        auth_query: SessionCredentialsQuery,
        replay_download_parser: ReplayDownloadQueryParser,
        replay_download_query: ReplayDownloadQuery,
    ) -> None:
        self._exchange: StableReplayDownloadExchange = StableReplayDownloadExchange(
            auth_query=auth_query,
            replay_download_parser=replay_download_parser,
            replay_download_query=replay_download_query,
        )

    async def __call__(self, request: Request) -> Response:
        """Stable replay download request を exchange に委譲する.

        Args:
            request: Starlette request.

        Returns:
            Stable replay download の HTTP response.

        Raises:
            Exchange の想定外例外をそのまま送出する.

        Constraints:
            Request body は読まず, query params だけを使う.
        """

        return await self._exchange.respond(request.query_params)


def _response_from_query_result(result: ReplayDownloadQueryResult) -> Response:
    if result.branch is ReplayDownloadBranch.SUCCESS:
        if result.response_body is None:
            return _empty_response(HTTPStatus.NOT_FOUND)
        return Response(
            content=result.response_body.payload,
            headers={
                "Content-Disposition": _SUCCESS_CONTENT_DISPOSITION,
                "Content-Type": _SUCCESS_CONTENT_TYPE,
            },
            status_code=HTTPStatus.OK,
        )

    if result.branch is ReplayDownloadBranch.AUTH_FAILURE:
        return _empty_response(HTTPStatus.UNAUTHORIZED)

    if result.branch in _EMPTY_NOT_FOUND_BRANCHES:
        return _empty_response(HTTPStatus.NOT_FOUND)

    return _empty_response(HTTPStatus.NOT_FOUND)


def _empty_response(status_code: HTTPStatus) -> Response:
    return Response(content=b"", status_code=status_code)


__all__ = [
    "ReplayDownloadHandler",
    "StableReplayDownloadExchange",
]
