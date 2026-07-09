"""Stable legacy replay download handler."""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import structlog
from starlette.responses import Response

from osu_server.domain.compatibility.stable import ReplayDownloadBranch
from osu_server.services.commands.scores.replay_download_accounting import (
    ReplayDownloadAccountingInput,
)
from osu_server.services.queries.identity import SessionCredentialsQueryInput
from osu_server.services.queries.scores import ReplayDownloadQueryInput

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from starlette.requests import Request

    from osu_server.services.commands.scores.replay_download_accounting import (
        ReplayDownloadAccountingUseCase,
    )
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
logger: structlog.stdlib.BoundLogger = cast(
    "structlog.stdlib.BoundLogger",
    structlog.get_logger(__name__),
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class StableReplayDownloadExchange:
    """Stable replay download の auth, parse, query orchestration を行う.

    引数:
        auth_query: Stable legacy credential を検証する query boundary.
        replay_download_parser: Confirmed replay download query keys を parse する mapper.
        replay_download_query: Replay download branch を解決する query use-case.
        replay_download_accounting: Success branch の best-effort accounting command.
        now_func: Accounting input 用の現在時刻 provider.

    戻り値:
        Class のため戻り値はない.

    例外:
        なし.

    制約:
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
        replay_download_accounting: ReplayDownloadAccountingUseCase | None = None,
        now_func: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._auth_query: SessionCredentialsQuery = auth_query
        self._replay_download_parser: ReplayDownloadQueryParser = replay_download_parser
        self._replay_download_query: ReplayDownloadQuery = replay_download_query
        self._replay_download_accounting: ReplayDownloadAccountingUseCase | None = (
            replay_download_accounting
        )
        self._now_func: Callable[[], datetime] = now_func

    async def respond(self, query: Mapping[str, str]) -> Response:
        """Stable replay download query を HTTP response に変換する.

        引数:
            query: Starlette QueryParams 互換または plain mapping.

        戻り値:
            Auth failure は empty 401. Malformed parse と unavailable branch は
            empty 404. Success branch は target-compatible body と download
            header を返す.

        例外:
            Query use-case の想定外例外はそのまま送出する.

        制約:
            Raw query values, credential values, storage detail は response に含めない.
        """

        auth_query_result = await self._auth_query.execute(
            SessionCredentialsQueryInput(
                username=query.get("u"),
                password_md5=query.get("h"),
            ),
        )
        auth_result = auth_query_result.outcome
        if auth_result.failure is not None or auth_result.user_id is None:
            return _empty_response(HTTPStatus.UNAUTHORIZED)

        user_id = auth_result.user_id

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
        await self._account_successful_download(viewer_user_id=user_id, result=result)
        return _response_from_query_result(result)

    async def _account_successful_download(
        self,
        *,
        viewer_user_id: int,
        result: ReplayDownloadQueryResult,
    ) -> None:
        if self._replay_download_accounting is None:
            return

        if result.branch is not ReplayDownloadBranch.SUCCESS:
            return

        metadata = result.accounting_metadata
        if result.response_body is None or metadata is None:
            return

        try:
            _ = await self._replay_download_accounting.execute(
                ReplayDownloadAccountingInput(
                    score_id=metadata.score_id,
                    score_owner_user_id=metadata.score_owner_user_id,
                    viewer_user_id=viewer_user_id,
                    occurred_at=self._now_func(),
                )
            )
        except Exception as exc:
            logger.warning(
                "replay_download_accounting_failed",
                operation="accounting_command",
                score_id=metadata.score_id,
                viewer_user_id=viewer_user_id,
                score_owner_user_id=metadata.score_owner_user_id,
                outcome="failed",
                exception_type=type(exc).__name__,
            )


class ReplayDownloadHandler:
    """Starlette adapter for `GET /web/osu-getreplay.php`.

    引数:
        auth_query: Stable legacy credential を検証する query boundary.
        replay_download_parser: Replay download query parser.
        replay_download_query: Replay download query use-case.
        replay_download_accounting: Success branch 後の best-effort accounting command.
        now_func: Accounting input 用の現在時刻 provider.

    戻り値:
        Class のため戻り値はない.

    例外:
        なし.

    制約:
        Route registration と DI wiring は後続 task が所有する.
    """

    def __init__(
        self,
        *,
        auth_query: SessionCredentialsQuery,
        replay_download_parser: ReplayDownloadQueryParser,
        replay_download_query: ReplayDownloadQuery,
        replay_download_accounting: ReplayDownloadAccountingUseCase | None = None,
        now_func: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._exchange: StableReplayDownloadExchange = StableReplayDownloadExchange(
            auth_query=auth_query,
            replay_download_parser=replay_download_parser,
            replay_download_query=replay_download_query,
            replay_download_accounting=replay_download_accounting,
            now_func=now_func,
        )

    async def __call__(self, request: Request) -> Response:
        """Stable replay download request を exchange に委譲する.

        引数:
            request: Starlette request.

        戻り値:
            Stable replay download の HTTP response.

        例外:
            Exchange の想定外例外をそのまま送出する.

        制約:
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

    msg = f"unhandled replay download branch: {result.branch!r}"
    raise AssertionError(msg)


def _empty_response(status_code: HTTPStatus) -> Response:
    return Response(content=b"", status_code=status_code)


__all__ = [
    "ReplayDownloadHandler",
    "StableReplayDownloadExchange",
]
