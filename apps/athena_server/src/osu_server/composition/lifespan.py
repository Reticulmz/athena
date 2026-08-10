"""Starlette applicationのlifespanを管理するfactoryとcontext managerを提供する.

Dishka application container,route handler,version metadataをstartup時に準備し,
lifespan終了時にcontainerをcloseする.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine
from taskiq import AsyncBroker

from osu_server.composition.health import check_infrastructure, get_version_info
from osu_server.composition.providers.container import make_app_container
from osu_server.config import AppConfig, load_config
from osu_server.domain.beatmaps import DirectSearchBackend
from osu_server.infrastructure.logging import setup_logging
from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
from osu_server.transports.stable.web_legacy.direct import (
    StableDirectPointLookupHandler,
    StableDirectSearchHandler,
)
from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
from osu_server.transports.stable.web_legacy.replay_download import ReplayDownloadHandler
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable

    from dishka import AsyncContainer, Provider
    from starlette.applications import Starlette


async def _initialize_dishka_app_container(container: AsyncContainer) -> None:
    """Starlette applicationが使用するDishka APP scope dependencyを先行解決する.

    Args:
        container (AsyncContainer): application用に構築済みのDishka container.

    Returns:
        None: configuration,infrastructure,HTTP handlerを一度ずつ解決したことを示す.
    """
    config = await container.get(AppConfig)
    _ = await container.get(AsyncEngine)
    _ = await container.get(AsyncBroker)
    _ = await container.get(httpx.AsyncClient)
    if config.osu_direct_validate_sql_search_backend_on_startup:
        backend = await container.get(DirectSearchBackend)
        await backend.validate()
    _ = await container.get(BanchoEndpoint)
    _ = await container.get(RegistrationHandler)
    _ = await container.get(GetscoresHandler)
    _ = await container.get(StableDirectSearchHandler)
    _ = await container.get(StableDirectPointLookupHandler)
    _ = await container.get(ScoreSubmitHandler)
    _ = await container.get(ReplayDownloadHandler)


def create_lifespan(
    provider_overrides: Iterable[Provider] = (),
):
    """明示したprovider overrideに束縛したStarlette lifespan factoryを作成する.

    Args:
        provider_overrides (Iterable[Provider]): application containerへ追加するDishka provider.

    Returns:
        Callable[[Starlette], AbstractAsyncContextManager[None]]: 指定providerを利用して
            startup/shutdownを実行するStarlette lifespan factory.
    """

    @asynccontextmanager
    async def configured_lifespan(app: Starlette) -> AsyncGenerator[None]:
        """指定provider overrideでapplication lifespanを実行する.

        Args:
            app (Starlette): lifespan stateを初期化するapplication.

        Yields:
            None: startup完了後からshutdown開始前までapplicationを実行可能にする.
        """
        async with _run_lifespan(app, provider_overrides=provider_overrides):
            yield

    return configured_lifespan


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncGenerator[None]:
    """明示provider overrideなしでapplication lifespanを実行する.

    Args:
        app (Starlette): lifespan stateを初期化するapplication.

    Yields:
        None: startup完了後からshutdown開始前までapplicationを実行可能にする.
    """
    async with _run_lifespan(app, provider_overrides=()):
        yield


@asynccontextmanager
async def _run_lifespan(
    app: Starlette,
    *,
    provider_overrides: Iterable[Provider],
) -> AsyncGenerator[None]:
    """アプリケーションcontainerとroute handlerを準備してlifespanを実行する.

    Args:
        app (Starlette): container,handler,version metadataをstateへ保存するapplication.
        provider_overrides (Iterable[Provider]): production provider graphへ追加するDishka
            provider.

    Yields:
        None: request handlerが必要とするstateを設定したapplication実行期間.

    Notes:
        test環境では`check_infrastructure()`を呼ばない. container構築後に発生した例外でも
        `finally`でcontainerをcloseする.
        startupでは`load_config()`,`make_app_container()`,dependencyの先行解決を順に行う.
        shutdownでは`dishka_container.close()`でDishka APP scope dependencyをfinalizeする.
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
        direct_search_handler = await dishka_container.get(StableDirectSearchHandler)
        direct_point_lookup_handler = await dishka_container.get(StableDirectPointLookupHandler)
        score_submit_handler = await dishka_container.get(ScoreSubmitHandler)
        replay_download_handler = await dishka_container.get(ReplayDownloadHandler)

        # Store on app.state for route endpoint access
        app.state.config = config
        app.state.bancho_endpoint = bancho_endpoint
        app.state.registration_handler = registration_handler
        app.state.getscores_handler = getscores_handler
        app.state.direct_search_handler = direct_search_handler
        app.state.direct_point_lookup_handler = direct_point_lookup_handler
        app.state.score_submit_handler = score_submit_handler
        app.state.replay_download_handler = replay_download_handler
        app.state.version_info = get_version_info()
        yield
    finally:
        await dishka_container.close()
