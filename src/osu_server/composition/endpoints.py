"""root ASGI application用のtransport endpoint adapterを提供する.

routeからapp stateに保存されたhandlerを取得し、stable transportのrequest処理へ委譲する.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
    from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
    from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
    from osu_server.transports.stable.web_legacy.replay_download import ReplayDownloadHandler
    from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler


class _ReplayDownloadAppState(Protocol):
    """replay download endpointが要求するapplication stateを表す.

    Attributes:
        replay_download_handler (ReplayDownloadHandler): replay download requestを処理する
            DI解決済みhandler.
    """

    replay_download_handler: ReplayDownloadHandler


class _ReplayDownloadApp(Protocol):
    """replay download endpointが要求するapplication interfaceを表す.

    Attributes:
        state (_ReplayDownloadAppState): replay download handlerを保持するapplication state.
    """

    state: _ReplayDownloadAppState


async def bancho_endpoint(request: Request) -> Response:
    """DIで解決済みのBanchoEndpointへrequestを委譲する.

    Args:
        request (Request): Bancho host routeへ届いたStarlette request.

    Returns:
        Response: BanchoEndpointが生成したHTTP response.

    Raises:
        Exception: BanchoEndpointが送出した例外を変換せず伝播する場合.
    """
    handler: BanchoEndpoint = request.app.state.bancho_endpoint  # pyright: ignore[reportAny]
    return await handler(request)


async def registration_endpoint(request: Request) -> Response:
    """DIで解決済みのRegistrationHandlerへrequestを委譲する.

    Args:
        request (Request): registration routeへ届いたStarlette request.

    Returns:
        Response: RegistrationHandlerが生成したHTTP response.

    Raises:
        Exception: RegistrationHandlerが送出した例外を変換せず伝播する場合.
    """
    handler: RegistrationHandler = request.app.state.registration_handler  # pyright: ignore[reportAny]
    return await handler(request)


async def getscores_endpoint(request: Request) -> Response:
    """DIで解決済みのGetscoresHandlerへrequestを委譲する.

    Args:
        request (Request): legacy getscores routeへ届いたStarlette request.

    Returns:
        Response: GetscoresHandlerが生成したHTTP response.

    Raises:
        Exception: GetscoresHandlerが送出した例外を変換せず伝播する場合.
    """
    handler: GetscoresHandler = request.app.state.getscores_handler  # pyright: ignore[reportAny]
    return await handler(request)


async def score_submit_endpoint(request: Request) -> Response:
    """DIで解決済みのScoreSubmitHandlerへrequestを委譲する.

    Args:
        request (Request): legacy score submission routeへ届いたStarlette request.

    Returns:
        Response: ScoreSubmitHandlerが生成したHTTP response.

    Raises:
        Exception: ScoreSubmitHandlerが送出した例外を変換せず伝播する場合.
    """
    handler: ScoreSubmitHandler = request.app.state.score_submit_handler  # pyright: ignore[reportAny]
    return await handler(request)


async def replay_download_endpoint(request: Request) -> Response:
    """DIで解決済みのReplayDownloadHandlerへrequestを委譲する.

    Args:
        request (Request): legacy replay download routeへ届いたStarlette request.

    Returns:
        Response: ReplayDownloadHandlerが生成したHTTP response.

    Raises:
        Exception: ReplayDownloadHandlerが送出した例外を変換せず伝播する場合.

    Notes:
        handlerは`request.app.state.replay_download_handler`に設定済みであることを前提とする.
    """
    app = cast("_ReplayDownloadApp", request.app)
    handler = app.state.replay_download_handler
    return await handler(request)
