"""Health endpointとinfrastructure health checkのunit testを提供する."""

from __future__ import annotations

import re
from http import HTTPStatus
from typing import TYPE_CHECKING, TypeVar, cast, final
from unittest.mock import patch

from glide import GlideClient
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from osu_server.app import get_version_info, health_check_endpoint, health_endpoint
from osu_server.config import AppConfig

if TYPE_CHECKING:
    import pytest

# ── Constants ──────────────────────────────────────────────────────────

_OK = HTTPStatus.OK
_UNAVAILABLE = HTTPStatus.SERVICE_UNAVAILABLE
_HEALTH_PATTERN = re.compile(r"^athena v[\d.]+ \(\w+\)\n$")

U = TypeVar("U")


@final
class FakeConnection:
    """PostgreSQL接続成功または失敗を再現するasync connection fakeを提供する.

    Attributes:
        _should_fail (bool): Trueの場合にexecuteでConnectionErrorを送出する設定.
    """

    def __init__(self, should_fail: bool) -> None:
        """接続実行時のfailure設定を初期化する.

        Args:
            should_fail (bool): executeでdatabase connection failureを再現するか.
        """
        self._should_fail = should_fail

    async def execute(self, _statement: object, *_args: object, **_kwargs: object) -> object:
        """Health check用statementを実行するか,設定済みfailureを送出する.

        Args:
            _statement (object): connection healthを確認するためのstatement.
            *_args (object): statement実行に渡される追加position argument.
            **_kwargs (object): statement実行に渡される追加keyword argument.

        Returns:
            object: connectionが正常な場合のNone.

        Raises:
            ConnectionError: should_failがTrueの場合.
        """
        if self._should_fail:
            raise ConnectionError("pg down")
        return None


@final
class FakeConnectionContext:
    """FakeConnectionを返しexceptionを抑制しないasync context managerを提供する.

    Attributes:
        _conn (FakeConnection): context内で公開するdatabase connection fake.
    """

    def __init__(self, conn: FakeConnection) -> None:
        """Context内で返すconnection fakeを設定する.

        Args:
            conn (FakeConnection): async withで返すconnection fake.
        """
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        """Context利用者へ設定済みconnection fakeを返す.

        Returns:
            FakeConnection: 初期化時に設定したconnection fake.
        """
        return self._conn

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> bool:
        """Context終了時にexceptionを抑制しない.

        Args:
            exc_type (object): context内で送出されたexception型またはNone.
            exc_val (object): context内で送出されたexception値またはNone.
            exc_tb (object): context内で送出されたtracebackまたはNone.

        Returns:
            bool: 常にFalse. context内のexceptionを呼び出し側へ伝播させる.
        """
        return False


@final
class FakeEngine:
    """設定に応じて成功または失敗するconnection contextを作るengine fakeを提供する.

    Attributes:
        _should_fail (bool): 作成したconnectionがexecute時に失敗するかを示す設定.
    """

    def __init__(self, should_fail: bool) -> None:
        """作成するconnectionのfailure設定を初期化する.

        Args:
            should_fail (bool): health checkのdatabase接続失敗を再現するか.
        """
        self._should_fail = should_fail

    def connect(self) -> FakeConnectionContext:
        """設定済みconnection fakeを返すasync context managerを作る.

        Returns:
            FakeConnectionContext: database接続を再現するcontext manager.
        """
        return FakeConnectionContext(FakeConnection(self._should_fail))


@final
class FakeValkey:
    """設定に応じてPONGまたはconnection failureを返すValkey fakeを提供する.

    Attributes:
        _should_fail (bool): Trueの場合にpingでConnectionErrorを送出する設定.
    """

    def __init__(self, should_fail: bool) -> None:
        """Ping failureを再現する設定を初期化する.

        Args:
            should_fail (bool): Valkey pingを失敗させるか.
        """
        self._should_fail = should_fail

    async def ping(self) -> str:
        """Valkey health checkのping結果を返す.

        Returns:
            str: 正常時のPONG response.

        Raises:
            ConnectionError: should_failがTrueの場合.
        """
        if self._should_fail:
            raise ConnectionError("valkey down")
        return "PONG"


@final
class FakeDishkaContainer:
    """Health endpointが取得するengineとValkey clientを返すDishka fakeを提供する.

    Attributes:
        _engine (FakeEngine): AsyncEngine requestに対して返すengine fake.
        _valkey (FakeValkey): GlideClient requestに対して返すValkey fake.
    """

    def __init__(self, engine: FakeEngine, valkey: FakeValkey) -> None:
        """Dependency typeごとに返すhealth check fakeを設定する.

        Args:
            engine (FakeEngine): PostgreSQL health checkに返すengine fake.
            valkey (FakeValkey): Valkey health checkに返すclient fake.
        """
        self._engine = engine
        self._valkey = valkey

    async def get(self, dependency_type: type[U]) -> U:
        """要求されたhealth dependency typeに対応するfakeを返す.

        Args:
            dependency_type (type[U]): AsyncEngineまたはGlideClientのdependency type.

        Returns:
            U: dependency typeに対応するengineまたはValkey fake.

        Raises:
            KeyError: 対応しないdependency typeが要求された場合.
        """
        if dependency_type is AsyncEngine:
            return cast("U", self._engine)
        if dependency_type is GlideClient:
            return cast("U", self._valkey)
        raise KeyError(f"{dependency_type!r} is not registered")


# ═══════════════════════════════════════════════════════════════════════
# get_version_info (Req 4.3)
# ═══════════════════════════════════════════════════════════════════════


class TestGetVersionInfo:
    """Package versionとcommit hashを返すget_version_infoを検証する."""

    def test_version_contains_pyproject_version(self) -> None:
        """Pyprojectのpackage versionがversion stringへ入る契約を検証する.

        Returns:
            None: versionが0.1.0であることを確認して完了する.
        """
        version, _commit = get_version_info()
        assert version == "0.1.0"

    def test_commit_hash_is_string(self) -> None:
        """Commit hashが空ではないstringとして返る契約を検証する.

        Returns:
            None: commit値の型と非空条件を確認して完了する.
        """
        _version, commit = get_version_info()
        assert isinstance(commit, str)
        assert len(commit) > 0

    def test_commit_hash_or_unknown(self) -> None:
        """Commit hashがhex stringまたはunknown fallbackとなる契約を検証する.

        Returns:
            None: 2種類の許容formatだけを確認して完了する.
        """
        _version, commit = get_version_info()
        assert commit == "unknown" or re.match(r"^[0-9a-f]+$", commit)

    def test_fallback_to_unknown_on_git_failure(self) -> None:
        """Git commandが利用不能ならunknown fallbackを返す契約を検証する.

        Returns:
            None: FileNotFoundError時のcommit値を確認して完了する.
        """
        with patch("subprocess.run", side_effect=FileNotFoundError):
            _version, commit = get_version_info()
            assert commit == "unknown"


# ═══════════════════════════════════════════════════════════════════════
# _health_endpoint (Req 4.1, 4.2)
# ═══════════════════════════════════════════════════════════════════════


class TestHealthEndpoint:
    """GET slash endpointがversion情報を持つplain text responseを返すことを検証する."""

    @staticmethod
    def _make_app(version: str = "0.1.0", commit: str = "abc1234") -> Starlette:
        """Health endpointだけを持つminimal Starlette appを構築する.

        Args:
            version (str): app stateへ設定するpackage version.
            commit (str): app stateへ設定するcommit hash.

        Returns:
            Starlette: root health endpointを公開するtest app.
        """
        app = Starlette(routes=[Route("/", health_endpoint, methods=["GET"])])
        app.state.version_info = (version, commit)
        return app

    def test_returns_200(self) -> None:
        """Root health endpointがHTTP 200を返す契約を検証する.

        Returns:
            None: response statusがOKであることを確認して完了する.
        """
        app = self._make_app()
        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.status_code == _OK

    def test_content_type_is_text_plain(self) -> None:
        """Root health endpointがtext/plain content typeを返す契約を検証する.

        Returns:
            None: response headerにtext/plainが含まれることを確認して完了する.
        """
        app = self._make_app()
        with TestClient(app) as client:
            resp = client.get("/")
            assert "text/plain" in resp.headers["content-type"]

    def test_body_contains_version(self) -> None:
        """Root health responseが設定済みversionを含む契約を検証する.

        Returns:
            None: response bodyにversion tokenがあることを確認して完了する.
        """
        app = self._make_app(version="0.1.0")
        with TestClient(app) as client:
            resp = client.get("/")
            assert "v0.1.0" in resp.text

    def test_body_contains_commit_hash(self) -> None:
        """Root health responseが設定済みcommit hashを含む契約を検証する.

        Returns:
            None: response bodyにcommit hashがあることを確認して完了する.
        """
        app = self._make_app(commit="abc1234")
        with TestClient(app) as client:
            resp = client.get("/")
            assert "abc1234" in resp.text

    def test_body_matches_format(self) -> None:
        """Root health responseがcanonical plain text formatを保つ契約を検証する.

        Returns:
            None: versionとcommitを含むexact response bodyを確認して完了する.
        """
        app = self._make_app(version="0.1.0", commit="abc1234")
        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.text == "athena v0.1.0 (abc1234)\n"

    def test_body_with_unknown_commit(self) -> None:
        """Unknown commit fallbackをroot health responseへ出す契約を検証する.

        Returns:
            None: unknownを含むexact response bodyを確認して完了する.
        """
        app = self._make_app(version="0.1.0", commit="unknown")
        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.text == "athena v0.1.0 (unknown)\n"

    def test_body_matches_pattern(self) -> None:
        """Root health responseが公開済みregular expression formatに一致することを検証する.

        Returns:
            None: response bodyがhealth patternと一致することを確認して完了する.
        """
        app = self._make_app()
        with TestClient(app) as client:
            resp = client.get("/")
            assert _HEALTH_PATTERN.match(resp.text)


# ═══════════════════════════════════════════════════════════════════════
# Config domain default (Req 3.1)
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# _health_check_endpoint (GET /health)
# ═══════════════════════════════════════════════════════════════════════


class TestHealthCheckEndpoint:
    """GET /healthがdatabaseとValkeyのinfrastructure healthを返すことを検証する."""

    @staticmethod
    def _make_container(
        *,
        postgres_ok: bool = True,
        valkey_ok: bool = True,
    ) -> FakeDishkaContainer:
        """DatabaseとValkeyの状態を設定したDishka fakeを構築する.

        Args:
            postgres_ok (bool): PostgreSQL health checkを成功させるか.
            valkey_ok (bool): Valkey health checkを成功させるか.

        Returns:
            FakeDishkaContainer: 設定済みdependency fakeを返すcontainer.
        """
        engine = FakeEngine(should_fail=not postgres_ok)
        valkey = FakeValkey(should_fail=not valkey_ok)
        return FakeDishkaContainer(engine, valkey)

    @classmethod
    def _make_app(
        cls,
        version: str = "0.1.0",
        commit: str = "abc1234",
        *,
        postgres_ok: bool = True,
        valkey_ok: bool = True,
    ) -> Starlette:
        """Health check endpointと設定済みcontainerを持つtest appを構築する.

        Args:
            version (str): response bodyへ入れるpackage version.
            commit (str): response bodyへ入れるcommit hash.
            postgres_ok (bool): database healthを成功させるか.
            valkey_ok (bool): Valkey healthを成功させるか.

        Returns:
            Starlette: GET /healthを公開するtest app.
        """
        app = Starlette(routes=[Route("/health", health_check_endpoint, methods=["GET"])])
        app.state.version_info = (version, commit)
        app.state.dishka_container = cls._make_container(
            postgres_ok=postgres_ok,
            valkey_ok=valkey_ok,
        )
        return app

    def test_healthy_returns_200(self) -> None:
        """全dependencyが正常ならhealth checkがHTTP 200を返す契約を検証する.

        Returns:
            None: response statusがOKであることを確認して完了する.
        """
        app = self._make_app()
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == _OK

    def test_healthy_response_body(self) -> None:
        """正常時のhealth responseがstatusとdependency checkを含む契約を検証する.

        Returns:
            None: version, commit, postgres, Valkeyの正常値を確認して完了する.
        """
        app = self._make_app(version="0.1.0", commit="abc1234")
        with TestClient(app) as client:
            data = cast("dict[str, object]", client.get("/health").json())
            assert data["status"] == "healthy"
            assert data["version"] == "0.1.0"
            assert data["commit"] == "abc1234"
            checks = cast("dict[str, object]", data["checks"])
            assert checks["postgres"] == "ok"
            assert checks["valkey"] == "ok"

    def test_content_type_is_json(self) -> None:
        """Health check endpointがapplication/jsonを返す契約を検証する.

        Returns:
            None: response content typeにapplication/jsonがあることを確認して完了する.
        """
        app = self._make_app()
        with TestClient(app) as client:
            resp = client.get("/health")
            assert "application/json" in resp.headers["content-type"]

    def test_postgres_down_returns_503(self) -> None:
        """PostgreSQL failure時にhealth checkがHTTP 503を返す契約を検証する.

        Returns:
            None: postgresだけがerrorとなるunhealthy responseを確認して完了する.
        """
        app = self._make_app(postgres_ok=False)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == _UNAVAILABLE
            data = cast("dict[str, object]", resp.json())
            assert data["status"] == "unhealthy"
            checks = cast("dict[str, object]", data["checks"])
            assert checks["postgres"] == "error"
            assert checks["valkey"] == "ok"

    def test_valkey_down_returns_503(self) -> None:
        """Valkey failure時にhealth checkがHTTP 503を返す契約を検証する.

        Returns:
            None: Valkeyだけがerrorとなるunhealthy responseを確認して完了する.
        """
        app = self._make_app(valkey_ok=False)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == _UNAVAILABLE
            data = cast("dict[str, object]", resp.json())
            assert data["status"] == "unhealthy"
            checks = cast("dict[str, object]", data["checks"])
            assert checks["postgres"] == "ok"
            assert checks["valkey"] == "error"

    def test_both_down_returns_503(self) -> None:
        """PostgreSQLとValkeyが共に失敗した場合のunhealthy responseを検証する.

        Returns:
            None: 両dependencyがerrorとなるHTTP 503 responseを確認して完了する.
        """
        app = self._make_app(postgres_ok=False, valkey_ok=False)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == _UNAVAILABLE
            data = cast("dict[str, object]", resp.json())
            assert data["status"] == "unhealthy"
            checks = cast("dict[str, object]", data["checks"])
            assert checks["postgres"] == "error"
            assert checks["valkey"] == "error"


# ═══════════════════════════════════════════════════════════════════════
# Config domain default (Req 3.1)
# ═══════════════════════════════════════════════════════════════════════


class TestConfigDomainDefault:
    """AppConfig.domainの既定値を検証する."""

    def test_domain_default_is_athena_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DOMAIN未設定時にathena.localhostを既定値にする契約を検証する.

        Args:
            monkeypatch (pytest.MonkeyPatch): required environmentを設定するpytest fixture.

        Returns:
            None: AppConfig.domainの既定値を確認して完了する.
        """
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/osu")
        monkeypatch.setenv("VALKEY_URL", "redis://localhost:6379/0")
        monkeypatch.delenv("DOMAIN", raising=False)

        config = AppConfig()  # pyright: ignore[reportCallIssue]
        assert config.domain == "athena.localhost"
