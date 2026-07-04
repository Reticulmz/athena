"""Starlette application factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Host, Mount, Route, Router

from osu_server.composition.endpoints import (
    bancho_endpoint,
    getscores_endpoint,
    registration_endpoint,
    replay_download_endpoint,
    score_submit_endpoint,
)
from osu_server.composition.health import health_check_endpoint, health_endpoint
from osu_server.composition.lifespan import create_lifespan
from osu_server.composition.middleware import RequestLoggingMiddleware
from osu_server.composition.starlette_integration import dishka_middleware
from osu_server.config import load_routing_config
from osu_server.transports.stable.web_legacy.bancho_connect import bancho_connect_endpoint

if TYPE_CHECKING:
    from collections.abc import Iterable

    from dishka import Provider


def create_app(provider_overrides: Iterable[Provider] = ()) -> Starlette:
    """Create and return the Starlette root application.

    Routing (domain from ``DOMAIN`` env var or ``.env.$ENVIRONMENT``,
    default ``athena.localhost``):
        - ``Host("c.$domain")`` -> bancho (POST /, GET /, GET /health)
        - ``Host("c<digits>.$domain")`` -> bancho stable fallback hosts
        - ``Host("ce.$domain")`` -> bancho stable fallback host
        - ``Host("osu.$domain")`` -> web_legacy (POST /users, GET /, GET /health)
        - ``GET /health`` -> DB/Redis health check (all routes)
        - Path-based fallbacks for local dev without DNS/subdomains:
            - ``GET /`` -> version info
            - ``GET /health`` -> health check
            - ``POST /web/users`` -> registration handler
    """
    domain = load_routing_config().domain

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
                "/web/osu-getreplay.php",
                endpoint=replay_download_endpoint,
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
        Host(f"c{{server:int}}.{domain}", app=bancho_routes),
        Host(f"ce.{domain}", app=bancho_routes),
        Host(f"osu.{domain}", app=web_routes),
        # Path-based fallbacks for local dev
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
        lifespan=create_lifespan(tuple(provider_overrides)),
        middleware=[
            dishka_middleware(),
            Middleware(RequestLoggingMiddleware),
        ],
    )
