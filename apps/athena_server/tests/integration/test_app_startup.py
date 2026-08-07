"""Starlette application startupとlifecycleのend-to-end contractを検証する.

Notes:
    In-memory provider testと実serviceを使うruntime smoke testを分離して検証する.
"""

from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from dishka import AsyncContainer
from starlette.testclient import TestClient

from osu_server.app import create_app as create_runtime_app
from osu_server.config import AppConfig, load_routing_config
from tests.support.app import create_in_memory_app
from tests.support.service_availability import require_tcp_service_url

if TYPE_CHECKING:
    from pathlib import Path

_BANCHO_URL = f"http://c.{load_routing_config().domain}/"


def _require_services() -> None:
    """Runtime smoke testに必要な外部serviceが利用可能であることを確認する.

    Returns:
        None: PostgreSQLとValkeyのTCP接続確認を完了する.

    Raises:
        pytest.skip.Exception: DATABASE_URLまたはVALKEY_URLのserviceが利用不能な場合.
    """
    _ = require_tcp_service_url("DATABASE_URL", default_port=5432)
    _ = require_tcp_service_url("VALKEY_URL", default_port=6379)


class TestInMemoryAppStartup:
    """外部serviceを必要としないapplication lifecycle contractを検証する."""

    def test_app_starts_and_responds(self, tmp_path: Path) -> None:
        """In-memory applicationがBancho hostへのPOSTへ200を返すcontractを検証する.

        Args:
            tmp_path (Path): test専用blob storageを作成するtemporary directory.

        Returns:
            None: running applicationのPOST responseがOKであることを確認して完了する.
        """
        app = create_in_memory_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(_BANCHO_URL)
            assert response.status_code == HTTPStatus.OK

    def test_lifespan_sets_state(self, tmp_path: Path) -> None:
        """Application lifespanがconfigとDishka containerをstateへ設定するcontractを検証する.

        Args:
            tmp_path (Path): test専用blob storageを作成するtemporary directory.

        Returns:
            None: startup後のapplication stateがtyped runtime dependencyを持つことを確認する.
        """
        app = create_in_memory_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False):
            assert hasattr(app.state, "config")
            assert hasattr(app.state, "dishka_container")
            assert isinstance(cast("object", app.state.config), AppConfig)
            assert isinstance(cast("object", app.state.dishka_container), AsyncContainer)

    def test_get_root_returns_ok(self, tmp_path: Path) -> None:
        """In-memory applicationがconnectivity probeのGETへ200を返すcontractを検証する.

        Args:
            tmp_path (Path): test専用blob storageを作成するtemporary directory.

        Returns:
            None: root GET responseがOKであることを確認して完了する.
        """
        app = create_in_memory_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/")
            assert response.status_code == HTTPStatus.OK


class TestRuntimeAppStartupSmoke:
    """実serviceを使うproduction provider graphのstartup smoke contractを検証する."""

    def test_runtime_app_get_root_returns_ok(self) -> None:
        """Production provider graphのapplicationがroot GETへ200を返すcontractを検証する.

        Returns:
            None: 外部service接続後のroot GET responseがOKであることを確認して完了する.

        Raises:
            pytest.skip.Exception: PostgreSQLまたはValkeyが利用不能な場合.
        """
        _require_services()
        app = create_runtime_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/")
            assert response.status_code == HTTPStatus.OK
