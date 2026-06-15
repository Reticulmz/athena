"""Application lifespan management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from osu_server.composition.health import check_infrastructure, get_version_info
from osu_server.composition.service_registry import register_services
from osu_server.config import load_config
from osu_server.infrastructure.di.providers import build_container
from osu_server.infrastructure.logging import setup_logging
from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

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
        bancho_endpoint = await container.resolve(BanchoEndpoint)
        registration_handler = await container.resolve(RegistrationHandler)
        getscores_handler = await container.resolve(GetscoresHandler)
        score_submit_handler = await container.resolve(ScoreSubmitHandler)

        # Store on app.state for route endpoint access
        app.state.config = config
        app.state.container = container
        app.state.bancho_endpoint = bancho_endpoint
        app.state.registration_handler = registration_handler
        app.state.getscores_handler = getscores_handler
        app.state.score_submit_handler = score_submit_handler
        app.state.version_info = get_version_info()
        yield
    finally:
        await container.shutdown()
