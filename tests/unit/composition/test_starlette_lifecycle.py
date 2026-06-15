"""Starlette lifecycle integration tests for Dishka composition."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette_dishka import FromDishka, inject
from tests.factories.config import make_app_config

import osu_server.composition.lifespan as lifespan_module
from osu_server.composition.lifespan import create_lifespan, lifespan
from osu_server.composition.providers.test import make_in_memory_runtime_provider_set
from osu_server.composition.starlette_integration import dishka_middleware
from osu_server.config import AppConfig

# starlette-dishka evaluates endpoint annotations at runtime.
_DISHKA_RUNTIME_HINTS = (Path, Request)


class _FailingDishkaContainer:
    close_called: bool

    def __init__(self) -> None:
        self.close_called = False

    async def get(self, dependency_type: object) -> object:
        _ = dependency_type
        msg = "dishka startup dependency is unavailable"
        raise RuntimeError(msg)

    async def close(self) -> None:
        self.close_called = True


@inject
async def _injected_config_endpoint(
    request: Request,
    *,
    config: FromDishka[AppConfig],
) -> PlainTextResponse:
    _ = request
    return PlainTextResponse(config.environment)


def test_starlette_lifespan_attaches_dishka_container(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_app_config(
        environment="test",
        blob_storage_local_root=str(tmp_path / "blobs"),
    )

    def setup_logging(_config: AppConfig) -> None:
        return None

    monkeypatch.setattr(lifespan_module, "load_config", lambda: config)
    monkeypatch.setattr(lifespan_module, "setup_logging", setup_logging)
    app = Starlette(
        routes=[Route("/config", _injected_config_endpoint)],
        lifespan=create_lifespan(
            (
                make_in_memory_runtime_provider_set(
                    blob_root=tmp_path / "blobs",
                ),
            )
        ),
        middleware=[dishka_middleware()],
    )

    with TestClient(app) as client:
        response = client.get("/config")

        assert response.status_code == 200
        assert response.text == "test"
        assert hasattr(app.state, "dishka_container")
        assert isinstance(cast("object", app.state.config), AppConfig)
        assert not hasattr(app.state, "container")


def test_starlette_lifespan_surfaces_dishka_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_app_config(environment="test")
    failing_container = _FailingDishkaContainer()

    def make_app_container(
        _config: AppConfig,
        *,
        overrides: object = (),
    ) -> _FailingDishkaContainer:
        _ = overrides
        return failing_container

    def setup_logging(_: AppConfig) -> None:
        return None

    monkeypatch.setattr(lifespan_module, "load_config", lambda: config)
    monkeypatch.setattr(lifespan_module, "setup_logging", setup_logging)
    monkeypatch.setattr(lifespan_module, "make_app_container", make_app_container)

    app = Starlette(lifespan=lifespan)

    with pytest.raises(RuntimeError, match="startup dependency"), TestClient(app):
        pass

    assert failing_container.close_called is True
