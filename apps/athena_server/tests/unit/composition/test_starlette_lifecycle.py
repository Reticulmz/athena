"""Dishka composition を組み込む Starlette lifecycle の契約を検証する."""

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
from osu_server.transports.stable.web_legacy.replay_download import ReplayDownloadHandler

# starlette-dishka evaluates endpoint annotations at runtime.
_DISHKA_RUNTIME_HINTS = (Path, Request)


class _FailingDishkaContainer:
    """Startup dependency 解決に失敗し close 呼出しを記録する container fake.

    Attributes:
        close_called (bool): close が呼び出されたか.
    """

    close_called: bool

    def __init__(self) -> None:
        """未 close 状態の失敗 container を初期化する."""
        self.close_called = False

    async def get(self, dependency_type: object) -> object:
        """要求された dependency にかかわらず startup failure を送出する.

        Args:
            dependency_type (object): Dishka が解決しようとする dependency type.

        Raises:
            RuntimeError: startup dependency が利用できない場合.
        """
        _ = dependency_type
        msg = "dishka startup dependency is unavailable"
        raise RuntimeError(msg)

    async def close(self) -> None:
        """Container が close されたことを記録する.

        Returns:
            None: close 状態を記録し, 呼び出し側へ値を返さない.
        """
        self.close_called = True


@inject
async def _injected_config_endpoint(
    request: Request,
    *,
    config: FromDishka[AppConfig],
) -> PlainTextResponse:
    """Dishka から注入された config environment を response として返す test endpoint.

    Args:
        request (Request): endpoint へ渡された HTTP request.
        config (FromDishka[AppConfig]): Dishka が解決して注入する app config.

    Returns:
        PlainTextResponse: config environment を本文に持つ response.
    """
    _ = request
    return PlainTextResponse(config.environment)


def test_starlette_lifespan_attaches_dishka_container(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """正常 startup が Dishka container と lifecycle state を app.state へ公開する契約を検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): lifecycle config と logging を差し替える fixture.
        tmp_path (Path): in-memory blob storage root を作る一時 directory.

    Returns:
        None: injected config response と公開済み app.state dependency を検証して完了する.
    """
    config = make_app_config(
        environment="test",
        blob_storage_local_root=str(tmp_path / "blobs"),
    )

    def setup_logging(_config: AppConfig, *, runtime_role: str = "app_server") -> None:
        """Test 中に実際の logging 設定を行わない stub.

        Args:
            _config (AppConfig): lifecycle が読み込んだ app config.
            runtime_role (str): lifecycleが渡すruntime role名.

        Returns:
            None: logging を変更せず, 呼び出し側へ値を返さない.
        """
        _ = runtime_role

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
        assert isinstance(
            cast("object", app.state.replay_download_handler),
            ReplayDownloadHandler,
        )
        assert not hasattr(app.state, "container")


def test_starlette_lifespan_surfaces_dishka_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup dependency failureがTestClient開始時に伝播しcontainerをcloseする.

    この契約を検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): container factory, config, logging を差し替える fixture.

    Returns:
        None: RuntimeError の伝播と失敗 container の close 記録を検証して完了する.
    """
    config = make_app_config(environment="test")
    failing_container = _FailingDishkaContainer()

    def make_app_container(
        _config: AppConfig,
        *,
        overrides: object = (),
    ) -> _FailingDishkaContainer:
        """Startup dependency 解決で失敗する固定 container を返す stub.

        Args:
            _config (AppConfig): lifecycle が読み込んだ app config.
            overrides (object): lifecycle が渡す provider override.

        Returns:
            _FailingDishkaContainer: 事前に作成した失敗 container.
        """
        _ = overrides
        return failing_container

    def setup_logging(_config: AppConfig, *, runtime_role: str = "app_server") -> None:
        """Test 中に実際の logging 設定を行わない stub.

        Args:
            _config (AppConfig): lifecycle が読み込んだ app config.
            runtime_role (str): lifecycleが渡すruntime role名.

        Returns:
            None: logging を変更せず, 呼び出し側へ値を返さない.
        """
        _ = runtime_role

    monkeypatch.setattr(lifespan_module, "load_config", lambda: config)
    monkeypatch.setattr(lifespan_module, "setup_logging", setup_logging)
    monkeypatch.setattr(lifespan_module, "make_app_container", make_app_container)

    app = Starlette(lifespan=lifespan)

    with pytest.raises(RuntimeError, match="startup dependency"), TestClient(app):
        pass

    assert failing_container.close_called is True
