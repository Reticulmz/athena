"""Transport endpoint adapters for the root ASGI application."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from osu_server.transports.bancho.handlers.login import LoginHandler
    from osu_server.transports.web_legacy.registration import RegistrationHandler


async def bancho_endpoint(request: Request) -> Response:
    """Delegate to LoginHandler resolved from DI."""
    handler: LoginHandler = request.app.state.login_handler  # pyright: ignore[reportAny]
    return await handler(request)


async def registration_endpoint(request: Request) -> Response:
    """Delegate to RegistrationHandler resolved from DI."""
    handler: RegistrationHandler = request.app.state.registration_handler  # pyright: ignore[reportAny]
    return await handler(request)
