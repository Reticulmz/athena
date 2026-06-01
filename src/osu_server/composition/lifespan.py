"""Application lifespan management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from osu_server.composition.health import check_infrastructure, get_version_info
from osu_server.composition.service_registry import register_services
from osu_server.config import load_config
from osu_server.infrastructure.di.providers import build_container
from osu_server.infrastructure.logging import setup_logging
from osu_server.transports.bancho.handlers.login import LoginHandler
from osu_server.transports.web_legacy.registration import RegistrationHandler

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.applications import Starlette


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncGenerator[None]:
    """Manage application startup and shutdown lifecycle.

    Startup:
        1. ``load_config()`` — read environment variables into ``AppConfig``
        2. ``build_container(config)`` — wire infrastructure components
        3. ``register_services(container, config)`` — wire higher-layer components
        4. ``container.initialize()`` — eagerly resolve all singletons

    Shutdown:
        1. ``container.shutdown()`` — dispose DB engine, close Valkey,
           close httpx client, etc.
    """
    config = load_config()
    setup_logging(config)
    container = await build_container(config)
    await register_services(container, config)
    try:
        await container.initialize()

        if config.environment != "test":
            await check_infrastructure(container)

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
