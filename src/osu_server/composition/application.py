"""Starlette application factory."""

from __future__ import annotations

import os

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Host, Mount, Route, Router

from osu_server.composition.endpoints import (
    bancho_endpoint,
    getscores_endpoint,
    registration_endpoint,
    score_submit_endpoint,
)
from osu_server.composition.health import health_check_endpoint, health_endpoint
from osu_server.composition.lifespan import lifespan
from osu_server.composition.middleware import RequestLoggingMiddleware
from osu_server.transports.stable.web_legacy.bancho_connect import bancho_connect_endpoint


def create_app() -> Starlette:
    """Create and return the Starlette root application.

    Routing (domain from ``DOMAIN`` env var, default ``athena.localhost``):
        - ``Host("c.$domain")`` -> bancho (POST /, GET /, GET /health)
        - ``Host("osu.$domain")`` -> web_legacy (POST /users, GET /, GET /health)
        - ``GET /health`` -> DB/Redis health check (all routes)
        - Path-based fallbacks for local dev without DNS/subdomains:
            - ``POST /`` -> bancho handler
            - ``GET /`` -> version info
            - ``GET /health`` -> health check
            - ``POST /web/users`` -> registration handler
    """
    domain = os.environ.get("DOMAIN", "athena.localhost")

    # bancho routes (c.$DOMAIN)
    bancho_routes = Router(
        routes=[
            Route("/", endpoint=bancho_endpoint, methods=["POST"]),
            Route("/", endpoint=health_endpoint, methods=["GET"]),
            Route("/health", endpoint=health_check_endpoint, methods=["GET"]),
        ],
    )

    # web_legacy routes (osu.$DOMAIN)
    web_routes = Router(
        routes=[
            Route("/", endpoint=health_endpoint, methods=["GET"]),
            Route("/health", endpoint=health_check_endpoint, methods=["GET"]),
            Route("/users", endpoint=registration_endpoint, methods=["POST"]),
            Route(
                "/web/bancho_connect.php",
                endpoint=bancho_connect_endpoint,
                methods=["GET"],
            ),
            Route(
                "/web/osu-osz2-getscores.php",
                endpoint=getscores_endpoint,
                methods=["GET"],
            ),
            Route(
                "/web/osu-submit-modular-selector.php",
                endpoint=score_submit_endpoint,
                methods=["POST"],
            ),
        ],
    )

    routes: list[Route | Mount | Host] = [
        # Subdomain-based routing
        Host(f"c.{domain}", app=bancho_routes),
        Host(f"osu.{domain}", app=web_routes),
        # Path-based fallbacks for local dev
        Route("/", endpoint=bancho_endpoint, methods=["POST"]),
        Route("/", endpoint=health_endpoint, methods=["GET"]),
        Route("/health", endpoint=health_check_endpoint, methods=["GET"]),
        Mount(
            "/web",
            routes=[
                Route("/users", endpoint=registration_endpoint, methods=["POST"]),
            ],
        ),
        # Future sub-app mount points
        Mount("/api/v2", routes=[]),
        Mount("/signalr", routes=[]),
    ]

    return Starlette(
        routes=routes,
        lifespan=lifespan,
        middleware=[Middleware(RequestLoggingMiddleware)],
    )
