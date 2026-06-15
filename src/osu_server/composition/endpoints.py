"""Transport endpoint adapters for the root ASGI application."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
    from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
    from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
    from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler


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
