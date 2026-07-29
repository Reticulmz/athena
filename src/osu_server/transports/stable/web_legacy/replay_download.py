"""Stable legacy replay download requestを認証してresponseへ変換するhandlerを提供する."""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import structlog
from starlette.background import BackgroundTask
from starlette.responses import Response

from osu_server.domain.compatibility.stable import ReplayDownloadBranch
from osu_server.services.commands.scores.replay_download_accounting import (
    ReplayDownloadAccountingInput,
)
from osu_server.services.queries.identity import SessionCredentialsQueryInput
from osu_server.services.queries.scores import ReplayDownloadQueryInput

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from starlette.background import BackgroundTask as StarletteBackgroundTask
    from starlette.requests import Request

    from osu_server.services.commands.scores.replay_download_accounting import (
        ReplayDownloadAccountingPublisher,
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
    """Replay download accounting用のUTC現在時刻を返す.

    Returns:
        datetime: UTC timezoneを持つ現在時刻.
    """
    return datetime.now(UTC)


class StableReplayDownloadExchange:
    """Stable replay downloadの認証, parse, queryを調整する.

    Attributes:
        _auth_query (SessionCredentialsQuery): legacy credentialを検証するquery.
        _replay_download_parser (ReplayDownloadQueryParser): query parameterをrequestへ
            変換するparser.
        _replay_download_query (ReplayDownloadQuery): replay可視性とbodyを取得するquery.
        _replay_download_accounting (ReplayDownloadAccountingPublisher | None):
            成功時のaccounting publisher.
        _now_func (Callable[[], datetime]): accounting inputへ設定する現在時刻provider.

    Notes:
        `u`と`h`は認証だけに渡す. 認証失敗時はparserとreplay queryを呼ばず, unavailable
        branchの内部原因はresponseに含めない.
    """

    def __init__(
        self,
        *,
        auth_query: SessionCredentialsQuery,
        replay_download_parser: ReplayDownloadQueryParser,
        replay_download_query: ReplayDownloadQuery,
        replay_download_accounting: ReplayDownloadAccountingPublisher | None = None,
        now_func: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Replay downloadの認証, parse, query依存を設定する.

        Args:
            auth_query (SessionCredentialsQuery): legacy credentialを検証するquery.
            replay_download_parser (ReplayDownloadQueryParser): queryをreplay requestへ
                変換するparser.
            replay_download_query (ReplayDownloadQuery): replay可視性とbodyを取得するquery.
            replay_download_accounting (ReplayDownloadAccountingPublisher | None):
                成功時のaccounting publisher.
            now_func (Callable[[], datetime]): accounting input用の現在時刻provider.
        """
        self._auth_query: SessionCredentialsQuery = auth_query
        self._replay_download_parser: ReplayDownloadQueryParser = replay_download_parser
        self._replay_download_query: ReplayDownloadQuery = replay_download_query
        self._replay_download_accounting: ReplayDownloadAccountingPublisher | None = (
            replay_download_accounting
        )
        self._now_func: Callable[[], datetime] = now_func

    async def respond(self, query: Mapping[str, str]) -> Response:
        """Stable replay download queryをHTTP responseへ変換する.

        Args:
            query (Mapping[str, str]): Starlette QueryParams互換またはplain mappingのquery values.

        Returns:
            Response: Athenaは認証失敗をUnauthorizedとしてbodyなしHTTP 401で返す. malformedまたは
                unavailableなreplayはNot FoundとしてbodyなしHTTP 404で返し, 成功時はdownload
                headerを持つresponseを返す.

        Notes:
            raw query value, credential, storage detailはresponseに含めない.
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
        accounting_task = self._account_successful_download_task(
            viewer_user_id=user_id,
            result=result,
        )
        return _response_from_query_result(result, background=accounting_task)

    def _account_successful_download_task(
        self,
        *,
        viewer_user_id: int,
        result: ReplayDownloadQueryResult,
    ) -> StarletteBackgroundTask | None:
        """成功したreplay downloadのbackground accounting taskを作成する.

        Args:
            viewer_user_id (int): replayを閲覧した認証済みuser ID.
            result (ReplayDownloadQueryResult): replay queryが解決したbranchとbody.

        Returns:
            StarletteBackgroundTask | None: accounting可能な成功branchにはtask, それ以外にはNone.
        """
        if self._replay_download_accounting is None:
            return None

        if result.branch is not ReplayDownloadBranch.SUCCESS:
            return None

        metadata = result.accounting_metadata
        if result.response_body is None or metadata is None:
            return None

        return BackgroundTask(
            self._publish_successful_download_accounting,
            score_id=metadata.score_id,
            score_owner_user_id=metadata.score_owner_user_id,
            viewer_user_id=viewer_user_id,
        )

    async def _publish_successful_download_accounting(
        self,
        *,
        score_id: int,
        score_owner_user_id: int,
        viewer_user_id: int,
    ) -> None:
        """成功したreplay downloadのaccounting eventをbest-effortで発行する.

        Args:
            score_id (int): downloadされたscore ID.
            score_owner_user_id (int): score所有者のuser ID.
            viewer_user_id (int): replayを閲覧したuser ID.

        Returns:
            None: accountingを発行するか失敗を記録し, responseへ値を返さず完了する.

        Notes:
            accounting input生成またはpublisherの失敗は記録して抑制し, download responseを変えない.
        """
        try:
            input_data = ReplayDownloadAccountingInput(
                score_id=score_id,
                score_owner_user_id=score_owner_user_id,
                viewer_user_id=viewer_user_id,
                occurred_at=self._now_func(),
            )
        except Exception as exc:
            logger.warning(
                "replay_download_accounting_failed",
                operation="accounting_input",
                score_id=score_id,
                viewer_user_id=viewer_user_id,
                score_owner_user_id=score_owner_user_id,
                outcome="failed",
                exception_type=type(exc).__name__,
            )
            return

        try:
            if self._replay_download_accounting is None:
                return
            await self._replay_download_accounting.publish(input_data)
        except Exception as exc:
            logger.warning(
                "replay_download_accounting_failed",
                operation="accounting_command",
                score_id=input_data.score_id,
                viewer_user_id=input_data.viewer_user_id,
                score_owner_user_id=input_data.score_owner_user_id,
                outcome="failed",
                exception_type=type(exc).__name__,
            )


class ReplayDownloadHandler:
    """`GET /web/osu-getreplay.php`をexchangeへ委譲するStarlette adapter.

    Attributes:
        _exchange (StableReplayDownloadExchange): queryをstable responseへ変換するexchange.
    """

    def __init__(
        self,
        *,
        auth_query: SessionCredentialsQuery,
        replay_download_parser: ReplayDownloadQueryParser,
        replay_download_query: ReplayDownloadQuery,
        replay_download_accounting: ReplayDownloadAccountingPublisher | None = None,
        now_func: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Replay download requestを処理するexchangeを構成する.

        Args:
            auth_query (SessionCredentialsQuery): legacy credentialを検証するquery.
            replay_download_parser (ReplayDownloadQueryParser): queryをreplay requestへ
                変換するparser.
            replay_download_query (ReplayDownloadQuery): replay可視性とbodyを取得するquery.
            replay_download_accounting (ReplayDownloadAccountingPublisher | None):
                成功時のaccounting publisher.
            now_func (Callable[[], datetime]): accounting input用の現在時刻provider.
        """
        self._exchange: StableReplayDownloadExchange = StableReplayDownloadExchange(
            auth_query=auth_query,
            replay_download_parser=replay_download_parser,
            replay_download_query=replay_download_query,
            replay_download_accounting=replay_download_accounting,
            now_func=now_func,
        )

    async def __call__(self, request: Request) -> Response:
        """Stable replay download requestをexchangeへ委譲する.

        Args:
            request (Request): stable clientから届いたGET request.

        Returns:
            Response: 認証とreplay queryの結果を反映したstable response.

        Notes:
            request bodyは読まず, query parameterだけを使う.
        """
        return await self._exchange.respond(request.query_params)


def _response_from_query_result(
    result: ReplayDownloadQueryResult,
    *,
    background: StarletteBackgroundTask | None = None,
) -> Response:
    """Replay query resultのbranchをstable HTTP responseへ変換する.

    Args:
        result (ReplayDownloadQueryResult): replay可視性, body, accounting metadataを持つquery結果.
        background (StarletteBackgroundTask | None): 成功responseの後に実行するaccounting task.

    Returns:
        Response: successにはreplay bodyのHTTP 200, auth failureには空のHTTP 401,
            非公開または欠損branchには空のHTTP 404 response.

    Raises:
        AssertionError: 未対応のReplayDownloadBranchを受け取った場合.
    """
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
            background=background,
        )

    if result.branch is ReplayDownloadBranch.AUTH_FAILURE:
        return _empty_response(HTTPStatus.UNAUTHORIZED)

    if result.branch in _EMPTY_NOT_FOUND_BRANCHES:
        return _empty_response(HTTPStatus.NOT_FOUND)

    msg = f"unhandled replay download branch: {result.branch!r}"
    raise AssertionError(msg)


def _empty_response(status_code: HTTPStatus) -> Response:
    """Bodyとdownload headerを持たないstable responseを構築する.

    Args:
        status_code (HTTPStatus): responseへ設定するHTTP status.

    Returns:
        Response: 空bodyと指定statusを持つresponse.
    """
    return Response(content=b"", status_code=status_code)


__all__ = [
    "ReplayDownloadHandler",
    "StableReplayDownloadExchange",
]
