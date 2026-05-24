"""Starlette root application with lifespan management.

Assembles the ASGI app, wires the DI container lifecycle,
and configures Host-based subdomain routing for bancho / web_legacy
with path-based fallbacks for local development.

This module serves as the **composition root** — it imports from all layers
to wire up the DI container.  import-linter layer contracts do not apply
to ``osu_server.app`` because it sits outside the layer hierarchy.
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog
import structlog.contextvars
import structlog.stdlib
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Host, Mount, Route, Router

from osu_server.config import AppConfig, load_config
from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.di.providers import build_container
from osu_server.infrastructure.logging import setup_logging
from osu_server.infrastructure.messaging.interfaces import EventBus
from osu_server.infrastructure.security.hibp import HIBPClient
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.user_repository import UserRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.repositories.redis.session_store import RedisSessionStore
from osu_server.repositories.sqlalchemy.role_repository import SQLAlchemyRoleRepository
from osu_server.repositories.sqlalchemy.user_repository import SQLAlchemyUserRepository
from osu_server.services.auth_service import AuthService
from osu_server.services.password_service import PasswordService
from osu_server.services.permission_service import PermissionService
from osu_server.transports.bancho.dispatch import PacketDispatcher, dispatcher
from osu_server.transports.bancho.handlers.login import LoginHandler
from osu_server.transports.bancho.listeners import setup_listeners
from osu_server.transports.web_legacy.registration import RegistrationHandler

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.requests import Request
    from starlette.responses import Response

    from osu_server.infrastructure.di.container import Container

logger: structlog.stdlib.BoundLogger = structlog.get_logger()  # pyright: ignore[reportAny]


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, status, and duration.

    Clears ``structlog.contextvars`` at the start of each request so that
    context bound during one request (e.g. ``user``, ``user_id``) does not
    leak into subsequent requests.
    """

    async def dispatch(  # pyright: ignore[reportImplicitOverride]
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Record an ``http_request`` event after the response is produced.

        Uses ``try/finally`` so that unhandled exceptions are still logged
        (with ``status=500``) before propagating.
        """
        structlog.contextvars.clear_contextvars()

        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            await logger.ainfo(
                "http_request",
                host=request.url.hostname,
                method=request.method,
                path=request.url.path,
                status=status,
                duration_ms=round(duration_ms, 2),
            )
        return response


def get_version_info() -> tuple[str, str]:
    """Return ``(package_version, commit_hash)`` for health responses.

    * ``package_version`` comes from ``importlib.metadata`` (pyproject.toml).
    * ``commit_hash`` is the short git HEAD hash; falls back to ``"unknown"``
      when git is unavailable or the repo is missing.
    """
    version = importlib.metadata.version("athena")

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        commit = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        commit = "unknown"

    return version, commit


async def _register_services(container: Container, config: AppConfig) -> None:
    """Register repository, service, and transport-layer components.

    Called from the composition root (lifespan) after infrastructure-layer
    registrations are complete.  Kept separate from ``build_container`` to
    respect the import-linter layer contracts (infrastructure must not import
    from repositories / services / transports).

    Also resolves ``EventBus`` and ``PacketQueue`` to wire domain event
    listeners via ``setup_listeners()``.
    """
    session_factory = await container.resolve(async_sessionmaker[AsyncSession])
    hibp_client = await container.resolve(HIBPClient)
    country_resolver = await container.resolve(CountryResolver)
    redis = await container.resolve(Redis)

    # -- SessionStore (singleton, environment-based switching) -----------------
    if config.environment == "test":
        container.register_singleton(SessionStore, InMemorySessionStore)
    else:
        container.register_singleton(
            SessionStore,
            lambda: RedisSessionStore(redis, ttl=config.session_ttl),
        )

    session_store = await container.resolve(SessionStore)

    # -- PasswordService (singleton) ------------------------------------------
    password_service = PasswordService(
        hibp_client=hibp_client,
        banned_passwords=config.banned_passwords,
    )
    container.register_singleton(PasswordService, lambda: password_service)

    # -- UserRepository (singleton, environment-based switching) ---------------
    if config.environment == "test":
        container.register_singleton(UserRepository, InMemoryUserRepository)
    else:
        container.register_singleton(
            UserRepository,
            lambda: SQLAlchemyUserRepository(session_factory),
        )

    # -- RoleRepository (singleton, environment-based switching) ---------------
    if config.environment == "test":
        container.register_singleton(RoleRepository, InMemoryRoleRepository)
    else:
        container.register_singleton(
            RoleRepository,
            lambda: SQLAlchemyRoleRepository(session_factory),
        )

    # -- PermissionService (singleton) ----------------------------------------
    role_repo = await container.resolve(RoleRepository)
    permission_service = PermissionService(role_repo=role_repo)
    container.register_singleton(PermissionService, lambda: permission_service)

    # -- AuthService (singleton) ----------------------------------------------
    user_repo = await container.resolve(UserRepository)
    auth_service = AuthService(
        user_repo=user_repo,
        role_repo=role_repo,
        password_service=password_service,
        permission_service=permission_service,
        session_store=session_store,
    )
    container.register_singleton(AuthService, lambda: auth_service)

    # -- LoginHandler (singleton) ---------------------------------------------
    packet_queue = await container.resolve(PacketQueue)
    eventbus = await container.resolve(EventBus)

    setup_listeners(eventbus, packet_queue)

    login_handler = LoginHandler(
        auth_service=auth_service,
        session_store=session_store,
        country_resolver=country_resolver,
        packet_queue=packet_queue,
        packet_dispatcher=dispatcher,
        session_ttl=config.session_ttl,
        max_request_body_size=config.max_request_body_size,
    )
    container.register_singleton(LoginHandler, lambda: login_handler)

    # -- RegistrationHandler (singleton) --------------------------------------
    registration_handler = RegistrationHandler(auth_service=auth_service)
    container.register_singleton(RegistrationHandler, lambda: registration_handler)

    # -- PacketDispatcher (singleton) -----------------------------------------
    container.register_singleton(PacketDispatcher, lambda: dispatcher)


async def _check_infrastructure(container: Container) -> None:
    """Verify PostgreSQL and Redis connectivity at startup.

    Raises on failure so the server refuses to start with broken dependencies.
    """
    engine = await container.resolve(AsyncEngine)
    async with engine.connect() as conn:
        _ = await conn.execute(text("SELECT 1"))
    logger.info("startup_health_check", service="postgresql", status="ok")

    redis = await container.resolve(Redis)
    await redis.ping()  # pyright: ignore[reportUnknownMemberType]
    logger.info("startup_health_check", service="redis", status="ok")


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncGenerator[None]:
    """Manage application startup and shutdown lifecycle.

    Startup:
        1. ``load_config()`` — read environment variables into ``AppConfig``
        2. ``build_container(config)`` — wire infrastructure components
        3. ``_register_services(container, config)`` — wire higher-layer components
        4. ``container.initialize()`` — eagerly resolve all singletons

    Shutdown:
        1. ``container.shutdown()`` — dispose DB engine, close Redis,
           close httpx client, etc.
    """
    config = load_config()
    setup_logging(config)
    container = await build_container(config)
    await _register_services(container, config)
    try:
        await container.initialize()

        if config.environment != "test":
            await _check_infrastructure(container)

        # Resolve handlers from DI container
        login_handler = await container.resolve(LoginHandler)
        registration_handler = await container.resolve(RegistrationHandler)

        # Store on app.state for route endpoint access
        app.state.config = config
        app.state.container = container
        app.state.login_handler = login_handler
        app.state.registration_handler = registration_handler
        app.state.version_info = get_version_info()
        yield
    finally:
        await container.shutdown()


async def _bancho_endpoint(request: Request) -> Response:
    """Delegate to LoginHandler resolved from DI."""
    handler: LoginHandler = request.app.state.login_handler  # pyright: ignore[reportAny]
    return await handler(request)


async def _registration_endpoint(request: Request) -> Response:
    """Delegate to RegistrationHandler resolved from DI."""
    handler: RegistrationHandler = request.app.state.registration_handler  # pyright: ignore[reportAny]
    return await handler(request)


async def _health_endpoint(request: Request) -> PlainTextResponse:
    """Return a plain-text health response with version and commit hash."""
    version, commit = request.app.state.version_info  # pyright: ignore[reportAny]
    return PlainTextResponse(f"athena v{version} ({commit})\n")


async def _health_check_endpoint(request: Request) -> JSONResponse:
    """Return infrastructure health status with DB and Redis connectivity checks."""
    version, commit = request.app.state.version_info  # pyright: ignore[reportAny]
    container: Container = request.app.state.container  # pyright: ignore[reportAny]

    checks: dict[str, str] = {}

    try:
        engine = await container.resolve(AsyncEngine)
        async with engine.connect() as conn:
            _ = await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "error"

    try:
        redis = await container.resolve(Redis)
        await redis.ping()  # pyright: ignore[reportUnknownMemberType]
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    all_healthy = all(v == "ok" for v in checks.values())

    return JSONResponse(
        {
            "status": "healthy" if all_healthy else "unhealthy",
            "version": version,
            "commit": commit,
            "checks": checks,
        },
        status_code=200 if all_healthy else 503,
    )


def create_app() -> Starlette:
    """Create and return the Starlette root application.

    Routing (domain from ``DOMAIN`` env var, default ``athena.localhost``):
        - ``Host("c.$domain")`` → bancho (POST /, GET /, GET /health)
        - ``Host("osu.$domain")`` → web_legacy (POST /users, GET /, GET /health)
        - ``GET /health`` → DB/Redis health check (all routes)
        - Path-based fallbacks for local dev without DNS/subdomains:
            - ``POST /`` → bancho handler
            - ``GET /`` → version info
            - ``GET /health`` → health check
            - ``POST /web/users`` → registration handler
    """
    domain = os.environ.get("DOMAIN", "athena.localhost")

    # bancho routes (c.$DOMAIN)
    bancho_routes = Router(
        routes=[
            Route("/", endpoint=_bancho_endpoint, methods=["POST"]),
            Route("/", endpoint=_health_endpoint, methods=["GET"]),
            Route("/health", endpoint=_health_check_endpoint, methods=["GET"]),
        ],
    )

    # web_legacy routes (osu.$DOMAIN)
    web_routes = Router(
        routes=[
            Route("/", endpoint=_health_endpoint, methods=["GET"]),
            Route("/health", endpoint=_health_check_endpoint, methods=["GET"]),
            Route("/users", endpoint=_registration_endpoint, methods=["POST"]),
        ],
    )

    routes: list[Route | Mount | Host] = [
        # Subdomain-based routing
        Host(f"c.{domain}", app=bancho_routes),
        Host(f"osu.{domain}", app=web_routes),
        # Path-based fallbacks for local dev
        Route("/", endpoint=_bancho_endpoint, methods=["POST"]),
        Route("/", endpoint=_health_endpoint, methods=["GET"]),
        Route("/health", endpoint=_health_check_endpoint, methods=["GET"]),
        Mount(
            "/web",
            routes=[
                Route("/users", endpoint=_registration_endpoint, methods=["POST"]),
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


app: Starlette = create_app()
