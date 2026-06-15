"""Starlette lifecycle integration tests for Dishka composition."""

from __future__ import annotations

from typing import TypeVar, cast, final

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette_dishka import FromDishka, inject
from tests.factories.config import make_app_config

import osu_server.composition.lifespan as lifespan_module
from osu_server.composition.lifespan import lifespan
from osu_server.composition.starlette_integration import dishka_middleware
from osu_server.config import AppConfig

# starlette-dishka evaluates endpoint annotations at runtime.
_DISHKA_RUNTIME_HINTS = (Request,)

T = TypeVar("T")


@final
class _FakeLegacyContainer:
    initialized: bool
    shutdown_called: bool

    def __init__(self) -> None:
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self) -> None:
        self.initialized = True

    async def resolve(self, interface: type[T]) -> T:
        return cast("T", _FakeHandler(interface.__name__))

    async def shutdown(self) -> None:
        self.shutdown_called = True


@final
class _FakeHandler:
    name: str

    def __init__(self, name: str) -> None:
        self.name = name


@inject
async def _injected_config_endpoint(
    request: Request,
    *,
    config: FromDishka[AppConfig],
) -> PlainTextResponse:
    _ = request
    return PlainTextResponse(config.environment)


@pytest.fixture
def fake_legacy_container(monkeypatch: pytest.MonkeyPatch) -> _FakeLegacyContainer:
    config = make_app_config(environment="test")
    container = _FakeLegacyContainer()

    async def build_container(_: AppConfig) -> _FakeLegacyContainer:
        return container

    async def register_services(
        _container: _FakeLegacyContainer,
        _config: AppConfig,
    ) -> None:
        return None

    def setup_logging(_config: AppConfig) -> None:
        return None

    monkeypatch.setattr(lifespan_module, "load_config", lambda: config)
    monkeypatch.setattr(lifespan_module, "setup_logging", setup_logging)
    monkeypatch.setattr(lifespan_module, "build_container", build_container)
    monkeypatch.setattr(lifespan_module, "register_services", register_services)
    return container


def test_starlette_lifespan_attaches_and_closes_dishka_container(
    fake_legacy_container: _FakeLegacyContainer,
) -> None:
    app = Starlette(
        routes=[Route("/config", _injected_config_endpoint)],
        lifespan=lifespan,
        middleware=[dishka_middleware()],
    )

    with TestClient(app) as client:
        response = client.get("/config")

        assert response.status_code == 200
        assert response.text == "test"
        assert hasattr(app.state, "dishka_container")
        assert isinstance(cast("object", app.state.config), AppConfig)
        assert fake_legacy_container.initialized is True

    assert fake_legacy_container.shutdown_called is True
