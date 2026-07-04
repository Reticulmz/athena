"""Transport endpoint adapters for the root ASGI application."""

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
    replay_download_handler: ReplayDownloadHandler


class _ReplayDownloadApp(Protocol):
    state: _ReplayDownloadAppState


async def bancho_endpoint(request: Request) -> Response:
    """Delegate to BanchoEndpoint resolved from DI."""
    handler: BanchoEndpoint = request.app.state.bancho_endpoint  # pyright: ignore[reportAny]
    return await handler(request)


async def registration_endpoint(request: Request) -> Response:
    """Delegate to RegistrationHandler resolved from DI."""
    handler: RegistrationHandler = request.app.state.registration_handler  # pyright: ignore[reportAny]
    return await handler(request)


async def getscores_endpoint(request: Request) -> Response:
    """Delegate to GetscoresHandler resolved from DI."""
    handler: GetscoresHandler = request.app.state.getscores_handler  # pyright: ignore[reportAny]
    return await handler(request)


async def score_submit_endpoint(request: Request) -> Response:
    """Delegate to ScoreSubmitHandler resolved from DI."""
    handler: ScoreSubmitHandler = request.app.state.score_submit_handler  # pyright: ignore[reportAny]
    return await handler(request)


async def replay_download_endpoint(request: Request) -> Response:
    """DI で解決した ReplayDownloadHandler に委譲する.

    引数:
        request: Starlette request.

    戻り値:
        Replay download の HTTP response.

    例外:
        Handler の想定外例外をそのまま送出する.

    制約:
        Handler は `request.app.state.replay_download_handler` から解決する.
    """
    app = cast("_ReplayDownloadApp", request.app)
    handler = app.state.replay_download_handler
    return await handler(request)
