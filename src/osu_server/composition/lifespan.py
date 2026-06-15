"""Application lifespan management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine
from taskiq import AsyncBroker

from osu_server.composition.health import check_infrastructure, get_version_info
from osu_server.composition.providers.container import make_app_container
from osu_server.composition.service_registry import register_services
from osu_server.config import AppConfig, load_config
from osu_server.infrastructure.di.providers import build_container
from osu_server.infrastructure.logging import setup_logging
from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from dishka import AsyncContainer
    from starlette.applications import Starlette

    from osu_server.infrastructure.di.container import Container


async def _initialize_dishka_app_container(container: AsyncContainer) -> None:
    """Eagerly validate the Starlette app's Dishka APP-scope dependencies."""
    _ = await container.get(AppConfig)
    _ = await container.get(AsyncEngine)
    _ = await container.get(AsyncBroker)
    _ = await container.get(httpx.AsyncClient)


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncGenerator[None]:
    """Manage application startup and shutdown lifecycle.

    Startup:
        1. ``load_config()`` — read environment variables into ``AppConfig``
        2. ``make_app_container(config)`` — build the Dishka app graph
        3. ``build_container(config)`` — wire legacy infrastructure components
        4. ``register_services(container, config)`` — wire higher-layer components
        5. Eagerly validate app dependency graphs before serving

    Shutdown:
        1. ``container.shutdown()`` — close legacy managed dependencies
        2. ``dishka_container.close()`` — finalize Dishka APP-scope dependencies
    """
    config = load_config()
    setup_logging(config)
    dishka_container = make_app_container(config)
    container: Container | None = None
    app.state.dishka_container = dishka_container

    try:
        await _initialize_dishka_app_container(dishka_container)

        container = await build_container(config)
        await register_services(container, config)
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
        if container is not None:
            await container.shutdown()
        await dishka_container.close()
