"""Starlette root application with lifespan management.

Assembles the ASGI app, wires the DI container lifecycle,
and exposes placeholder routes / mount points for future sub-apps.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from osu_server.config import load_config
from osu_server.infrastructure.di.providers import build_container


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncGenerator[None]:
    """Manage application startup and shutdown lifecycle.

    Startup:
        1. ``load_config()`` — read environment variables into ``AppConfig``
        2. ``build_container(config)`` — wire all infrastructure components
        3. ``container.initialize()`` — eagerly resolve all singletons

    Shutdown:
        1. ``container.shutdown()`` — dispose DB engine, close Redis, etc.
    """
    config = load_config()
    container = await build_container(config)
    await container.initialize()

    app.state.config = config
    app.state.container = container

    yield

    await container.shutdown()


async def bancho_placeholder(_request: Request) -> Response:
    """Placeholder for the bancho binary protocol endpoint (POST /)."""
    return Response(status_code=200)


def create_app() -> Starlette:
    """Create and return the Starlette root application."""
    routes: list[Route | Mount] = [
        Route("/", endpoint=bancho_placeholder, methods=["POST"]),
        # Future sub-app mount points
        Mount("/web", routes=[]),
        Mount("/api/v2", routes=[]),
        Mount("/signalr", routes=[]),
    ]

    return Starlette(
        routes=routes,
        lifespan=lifespan,
    )


app: Starlette = create_app()
