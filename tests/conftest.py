"""test実行時の共有fixtureとruntime resource cleanupを提供する."""

from __future__ import annotations

import asyncio
import logging
import os
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable, Generator, Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from pathlib import Path
from typing import Protocol, cast, final

import pytest
import structlog
from glide import GlideClient
from taskiq_redis import ListQueueBroker

import osu_server.infrastructure.cache.valkey_client as valkey_module
from osu_server.shared.query_diagnostics import (
    QueryDiagnosticSummary,
    query_diagnostic_scope,
)

# ---------------------------------------------------------------------------
# Runtime resource tracking -- ensures sockets are closed after tests
# ---------------------------------------------------------------------------

_TEST_ENV_FILE = Path(".env.test")
_TEST_SERVICE_ENV_VARS = frozenset({"DATABASE_URL", "VALKEY_URL"})

type _ValkeyClientFactory = Callable[[str], Awaitable[GlideClient]]
type _BrokerInitializer = Callable[..., None]


class _AsyncCloseable(Protocol):
    """非同期close操作を公開するtest doubleの構造を表す."""

    async def close(self) -> None:
        """追跡済みresourceを非同期にcloseする.

        Returns:
            None: resourceをcloseし, 呼び出し側へ値を返さずに完了する.
        """
        ...


class _AsyncShutdownBroker(Protocol):
    """非同期shutdown操作を公開するbroker test doubleの構造を表す."""

    async def shutdown(self) -> None:
        """追跡済みbrokerを非同期にshutdownする.

        Returns:
            None: brokerをshutdownし, 呼び出し側へ値を返さずに完了する.
        """
        ...


class QueryBudget(Protocol):
    """SQL query数の上限を検証するfixture callableのcontractを表す."""

    def __call__(
        self,
        *,
        max_queries: int,
        name: str,
        duplicate_threshold: int = 2,
    ) -> AbstractContextManager[None]:
        """指定scopeのSQL query数を検証するcontext managerを作る.

        Args:
            max_queries (int): scope内で許可する最大SQL query数.
            name (str): failure messageに表示するredacted scope名.
            duplicate_threshold (int): duplicateと扱う同一SQL templateの最小回数.

        Returns:
            AbstractContextManager[None]: query数を計測して終了時に検証するcontext manager.

        Raises:
            ValueError: max_queriesが0未満の場合.
            AssertionError: scope内のquery数がmax_queriesを超える場合.
        """
        ...


@final
class RuntimeResourceTracker:
    """test suiteで生成されるruntime resourceとpatchを追跡する.

    Attributes:
        _glide_clients (list[weakref.ReferenceType[object]]): close対象のGlide client参照.
        _brokers (list[weakref.ReferenceType[object]]): shutdown対象のbroker参照.
        _original_create_valkey_client (_ValkeyClientFactory | None):
            patch前のValkey client factory.
        _original_list_queue_broker_init (_BrokerInitializer | None): patch前のbroker initializer.
    """

    _glide_clients: list[weakref.ReferenceType[object]]
    _brokers: list[weakref.ReferenceType[object]]
    _original_create_valkey_client: _ValkeyClientFactory | None
    _original_list_queue_broker_init: _BrokerInitializer | None

    def __init__(self) -> None:
        """空のresource追跡状態を初期化する."""
        self._glide_clients = []
        self._brokers = []
        self._original_create_valkey_client = None
        self._original_list_queue_broker_init = None

    def install_patches(self) -> None:
        """resourceを追跡するためruntime constructorをpatchする.

        Returns:
            None: constructorをpatchし, 呼び出し側へ値を返さずに完了する.
        """
        self._original_create_valkey_client = valkey_module.create_valkey_client
        self._original_list_queue_broker_init = ListQueueBroker.__init__

        async def tracked_create_valkey_client(valkey_url: str) -> GlideClient:
            """生成したGlide clientを追跡して返す.

            Args:
                valkey_url (str): 接続するValkey endpoint.

            Returns:
                GlideClient: 追跡登録済みのValkey client.

            Raises:
                RuntimeError: factory patchが未設定の場合.
            """
            original = self._original_create_valkey_client
            if original is None:
                msg = "Valkey client factory patch is not installed"
                raise RuntimeError(msg)
            client = await original(valkey_url)
            self._track_glide_client(client)
            return client

        tracker = self

        def tracked_broker_init(
            self: ListQueueBroker,
            *args: object,
            **kwargs: object,
        ) -> None:
            """生成したbrokerを追跡して元のinitializerを実行する.

            Args:
                self (ListQueueBroker): patch対象のbroker instance.
                args (object): 元のinitializerへ渡す位置引数.
                kwargs (object): 元のinitializerへ渡すkeyword引数.

            Returns:
                None: brokerを初期化して追跡し, 呼び出し側へ値を返さずに完了する.

            Raises:
                RuntimeError: initializer patchが未設定の場合.
            """
            original = tracker._original_list_queue_broker_init
            if original is None:
                msg = "ListQueueBroker initializer patch is not installed"
                raise RuntimeError(msg)
            original(self, *args, **kwargs)
            tracker._brokers.append(weakref.ref(self))

        valkey_module.create_valkey_client = tracked_create_valkey_client
        ListQueueBroker.__init__ = tracked_broker_init

    def restore_patches(self) -> None:
        """Test cleanup用にpatchしたruntime constructorを復元する.

        Returns:
            None: 元のconstructorを復元し, 呼び出し側へ値を返さずに完了する.
        """
        if self._original_create_valkey_client is not None:
            valkey_module.create_valkey_client = self._original_create_valkey_client
            self._original_create_valkey_client = None
        if self._original_list_queue_broker_init is not None:
            ListQueueBroker.__init__ = self._original_list_queue_broker_init
            self._original_list_queue_broker_init = None

    async def close_after_test(self) -> None:
        """test中に生成した追跡resourceをcloseまたはshutdownする.

        Returns:
            None: cleanupを完了し, 呼び出し側へ値を返さずに完了する.
        """
        for ref in self._glide_clients:
            client = ref()
            if client is not None:
                closeable = _as_async_closeable(client)
                if closeable is not None:
                    with suppress(Exception):
                        await closeable.close()
        self._glide_clients.clear()

        alive_brokers: list[weakref.ReferenceType[object]] = []
        for ref in self._brokers:
            broker = ref()
            if broker is not None:
                alive_brokers.append(ref)
                shutdown_broker = _as_async_shutdown_broker(broker)
                if shutdown_broker is not None:
                    with suppress(Exception):
                        await shutdown_broker.shutdown()
        self._brokers = alive_brokers
        if self._brokers:
            await asyncio.sleep(0)
        # _brokers is intentionally retained: module-level singleton brokers
        # can reconnect between tests and need closing after later tests too.

    def _track_glide_client(self, client: object) -> None:
        """後続のtest cleanup対象としてGlide clientを登録する.

        Args:
            client (object): weak referenceで保持できる生成済みclient.

        Returns:
            None: clientを登録し, 呼び出し側へ値を返さずに完了する.
        """
        self._glide_clients.append(weakref.ref(client))


def _as_async_closeable(value: object) -> _AsyncCloseable | None:
    """Close methodを持つ値を非同期close protocolとして返す.

    Args:
        value (object): close可能性を確認する値.

    Returns:
        _AsyncCloseable | None: close methodを持つ値. 持たない場合はNone.
    """
    if callable(getattr(value, "close", None)):
        return cast("_AsyncCloseable", value)
    return None


def _as_async_shutdown_broker(value: object) -> _AsyncShutdownBroker | None:
    """Shutdown methodを持つ値をbroker protocolとして返す.

    Args:
        value (object): shutdown可能性を確認する値.

    Returns:
        _AsyncShutdownBroker | None: shutdown methodを持つ値. 持たない場合はNone.
    """
    if callable(getattr(value, "shutdown", None)):
        return cast("_AsyncShutdownBroker", value)
    return None


_runtime_resources = RuntimeResourceTracker()


def _load_test_service_env_defaults() -> None:
    """os.environを直接読むtestへ.env.testのservice URLを公開する.

    Returns:
        None: 未設定のservice URLを環境へ設定し, 呼び出し側へ値を返さずに完了する.
    """
    if not _TEST_ENV_FILE.exists():
        return

    for raw_line in _TEST_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in _TEST_SERVICE_ENV_VARS:
            continue
        value = raw_value.strip().strip("\"'")
        _ = os.environ.setdefault(key, value)


@pytest.fixture(autouse=True)
async def close_runtime_resources() -> AsyncIterator[None]:
    """各test後に生成済みGlide clientとbrokerをcleanupする.

    Yields:
        None: test本体の実行権.
    """
    yield
    await _runtime_resources.close_after_test()


def pytest_configure(config: pytest.Config) -> None:
    """Test import前にenvironmentとresource追跡patchを設定する.

    Args:
        config (pytest.Config): pytestの実行設定.

    Returns:
        None: test用runtime設定を完了し, 呼び出し側へ値を返さずに完了する.
    """
    _ = config
    _ = os.environ.setdefault("ENVIRONMENT", "test")
    _load_test_service_env_defaults()
    _runtime_resources.install_patches()


def pytest_unconfigure(config: pytest.Config) -> None:
    """Test session終了時に元のruntime constructorを復元する.

    Args:
        config (pytest.Config): pytestの実行設定.

    Returns:
        None: constructorを復元し, 呼び出し側へ値を返さずに完了する.
    """
    _ = config
    _runtime_resources.restore_patches()


# ---------------------------------------------------------------------------
# structlog reset
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_structlog() -> Iterator[None]:
    """test前後にstructlogとroot loggerの状態を初期化する.

    Yields:
        None: logger cacheの影響を受けないtest実行権.
    """
    structlog.configure(cache_logger_on_first_use=False)

    yield

    structlog.configure(cache_logger_on_first_use=False)
    root = logging.getLogger()
    # Close all handlers (root + uvicorn loggers set up by setup_logging)
    all_handlers: list[logging.Handler] = list(root.handlers)
    for logger_name in ("uvicorn.error", "uvicorn.access"):
        all_handlers.extend(logging.getLogger(logger_name).handlers)
    for handler in all_handlers:
        handler.close()
    root.handlers.clear()
    for logger_name in ("uvicorn.error", "uvicorn.access"):
        logging.getLogger(logger_name).handlers.clear()
    root.setLevel(logging.WARNING)


@pytest.fixture
def query_budget() -> QueryBudget:
    """SQL query数の上限を検証するcontext manager factoryを提供する.

    Returns:
        QueryBudget: query数と重複templateを検証するcallable.

    Notes:
        context内の例外はbudget検証より優先して伝播する.
    """

    @contextmanager
    def budget(
        *,
        max_queries: int,
        name: str,
        duplicate_threshold: int = 2,
    ) -> Generator[None]:
        """scope内のSQL query数を記録し, 終了後に上限を検証する.

        Args:
            max_queries (int): scope内で許可する最大query数.
            name (str): failure messageに表示するredacted scope名.
            duplicate_threshold (int): duplicateと扱う同一SQL templateの最小回数.

        Yields:
            None: SQL queryを実行する検証対象scope.

        Raises:
            ValueError: max_queriesが0未満の場合.
            AssertionError: scope内のquery数がmax_queriesを超える場合.
        """
        if max_queries < 0:
            msg = "max_queries must be greater than or equal to 0"
            raise ValueError(msg)
        with query_diagnostic_scope(
            scope_kind="test",
            scope_name=name,
            duplicate_threshold=duplicate_threshold,
        ) as collector:
            yield
        summary = collector.summary()
        if summary.total_queries > max_queries:
            raise AssertionError(_format_query_budget_failure(summary, max_queries))

    return budget


def _format_query_budget_failure(
    summary: QueryDiagnosticSummary,
    max_queries: int,
) -> str:
    """Query budget超過を説明するfailure messageを組み立てる.

    Args:
        summary (QueryDiagnosticSummary): 計測済みquery診断の集計値.
        max_queries (int): 許可する最大query数.

    Returns:
        str: actual数とduplicate query情報を含むfailure message.
    """
    duplicate_lines = [
        " ".join(
            (
                f"  - count={duplicate.count}",
                f"fingerprint={duplicate.fingerprint}",
                f"sql_prefix={duplicate.sql_prefix!r}",
            )
        )
        for duplicate in summary.duplicate_queries
    ]
    duplicates = "\n".join(duplicate_lines) if duplicate_lines else "  - none"
    return "\n".join(
        (
            "SQL query budget exceeded",
            f"scope={summary.scope_kind}:{summary.scope_name}",
            f"actual={summary.total_queries}",
            f"allowed={max_queries}",
            f"duplicate_templates_total={summary.duplicate_templates_total}",
            f"duplicates_truncated={summary.duplicates_truncated}",
            "duplicates:",
            duplicates,
        )
    )
