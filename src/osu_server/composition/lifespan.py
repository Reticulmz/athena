"""Application lifespan management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine
from taskiq import AsyncBroker

from osu_server.composition.health import check_infrastructure, get_version_info
from osu_server.composition.providers.container import make_app_container
from osu_server.config import AppConfig, load_config
from osu_server.infrastructure.logging import setup_logging
from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable

    from dishka import AsyncContainer, Provider
    from starlette.applications import Starlette


async def _initialize_dishka_app_container(container: AsyncContainer) -> None:
    """Eagerly validate the Starlette app's Dishka APP-scope dependencies."""
    _ = await container.get(AppConfig)
    _ = await container.get(AsyncEngine)
    _ = await container.get(AsyncBroker)
    _ = await container.get(httpx.AsyncClient)
    _ = await container.get(BanchoEndpoint)
    _ = await container.get(RegistrationHandler)
    _ = await container.get(GetscoresHandler)
    _ = await container.get(ScoreSubmitHandler)


def create_lifespan(
    provider_overrides: Iterable[Provider] = (),
):
    """Create a Starlette lifespan bound to explicit provider overrides."""

    @asynccontextmanager
    async def configured_lifespan(app: Starlette) -> AsyncGenerator[None]:
        async with _run_lifespan(app, provider_overrides=provider_overrides):
            yield

    return configured_lifespan


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncGenerator[None]:
    """Manage application startup and shutdown lifecycle."""
    async with _run_lifespan(app, provider_overrides=()):
        yield


@asynccontextmanager
async def _run_lifespan(
    app: Starlette,
    *,
    provider_overrides: Iterable[Provider],
) -> AsyncGenerator[None]:
    """Manage application startup and shutdown lifecycle.

    Startup:
        1. ``load_config()`` — read environment variables into ``AppConfig``
        2. ``make_app_container(config)`` — build the Dishka app graph
        3. Eagerly validate app dependency graphs before serving

    Shutdown:
        1. ``dishka_container.close()`` — finalize Dishka APP-scope dependencies
    """
    config = load_config()
    setup_logging(config)
    dishka_container = make_app_container(config, overrides=provider_overrides)
    app.state.dishka_container = dishka_container

    try:
        await _initialize_dishka_app_container(dishka_container)

        if config.environment != "test":
            await check_infrastructure(dishka_container)

        bancho_endpoint = await dishka_container.get(BanchoEndpoint)
        registration_handler = await dishka_container.get(RegistrationHandler)
        getscores_handler = await dishka_container.get(GetscoresHandler)
        score_submit_handler = await dishka_container.get(ScoreSubmitHandler)

        # Store on app.state for route endpoint access
        app.state.config = config
        app.state.bancho_endpoint = bancho_endpoint
        app.state.registration_handler = registration_handler
        app.state.getscores_handler = getscores_handler
        app.state.score_submit_handler = score_submit_handler
        app.state.version_info = get_version_info()
        yield
    finally:
        await dishka_container.close()
