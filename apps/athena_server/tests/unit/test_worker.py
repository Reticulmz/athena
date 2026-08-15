"""Taskiq worker lifecycleのdependency設定とcleanup契約を検証する."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import httpx
import pytest
import structlog
from taskiq import Context, InMemoryBroker, TaskiqMessage, TaskiqState

import osu_server.worker as worker_module
from osu_server.composition.providers.container import make_worker_container
from osu_server.composition.providers.test import (
    TestProviderSet,
    make_in_memory_runtime_provider_set,
    replace_value,
)
from osu_server.config import AppConfig
from osu_server.jobs.chat_persistence import persist_private_message
from osu_server.jobs.osu_direct import (
    crawl_osu_direct_id_range,
    rebuild_osu_direct_external_index,
    rebuild_osu_direct_search_projection,
    sync_osu_direct_feed_window,
    update_osu_direct_external_index,
)
from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
)
from osu_server.services.commands.beatmaps.direct_catalog_sync import (
    DirectCatalogScheduler,
    DirectFeedSync,
    DirectRangeCrawl,
)
from osu_server.services.commands.beatmaps.direct_indexing import DirectIndexingCommands
from osu_server.services.commands.chat import (
    PersistChannelMessageUseCase,
    PersistPrivateMessageUseCase,
)
from osu_server.services.commands.scores.leaderboards import (
    RebuildBeatmapLeaderboardsForBeatmapsetUseCase,
    RebuildBeatmapLeaderboardsForUserUseCase,
)
from osu_server.services.commands.scores.performance import (
    ExecutePerformanceCalculationUseCase,
    ProcessPerformanceRecalculationBatchUseCase,
)
from osu_server.services.commands.scores.replay_download_accounting import (
    ReplayDownloadAccountingUseCase,
)
from osu_server.services.queries.chat import (
    ListPrivateMessagesQuery,
    ListPrivateMessagesQueryInput,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
    from pathlib import Path

    from dishka import AsyncContainer, Provider

    from osu_server.domain.beatmaps import BeatmapFetchTarget

    WorkerLifecycleHook = Callable[[TaskiqState], Awaitable[None]]


class FakeDishkaContainer:
    """close呼び出し回数を記録するAsyncContainer test doubleを表す.

    Attributes:
        close_calls (int): closeが完了した回数.
    """

    close_calls: int

    def __init__(self) -> None:
        """close記録を0件で初期化する."""
        self.close_calls = 0

    async def close(self) -> None:
        """Container close要求を記録する.

        Returns:
            None: close回数を増やして完了し,呼び出し側へ値を返さない.
        """
        self.close_calls += 1


class FailingWorkerContainer:
    """file fetch use caseの解決で失敗するworker container fakeを表す.

    Attributes:
        close_calls (int): cleanup時のclose呼び出し回数.
    """

    close_calls: int

    def __init__(self) -> None:
        """close記録を0件で失敗containerを初期化する."""
        self.close_calls = 0

    async def get(self, dependency_type: type[object]) -> object:
        """File fetch依存だけをRuntimeErrorにしてstartup失敗を再現する.

        Args:
            dependency_type (type[object]): workerがcontainerから解決しようとする依存型.

        Returns:
            object: file fetch以外の依存解決を表す無名object.

        Raises:
            RuntimeError: FetchBeatmapFileUseCaseの解決が要求された場合.
        """
        if dependency_type is FetchBeatmapFileUseCase:
            msg = "beatmap file fetch unavailable"
            raise RuntimeError(msg)
        return object()

    async def close(self) -> None:
        """失敗後のcontainer cleanupを記録する.

        Returns:
            None: close回数を増やして完了し,呼び出し側へ値を返さない.
        """
        self.close_calls += 1


@dataclass(frozen=True, slots=True)
class RecordedBeatmapFetch:
    """beatmap fetch taskへの入力を比較するための記録値を表す.

    Attributes:
        target_type (str): fetch targetの種別を表す文字列.
        target_key (str): targetを一意に特定する値.
    """

    target_type: str
    target_key: str


class FakeBeatmapFetchUseCase:
    """task adapterから渡されたbeatmap fetchを記録するuse case fakeを表す.

    Attributes:
        calls (list[BeatmapFetchTarget]): executeで受け取ったtargetの呼び出し順記録.
    """

    calls: list[BeatmapFetchTarget]

    def __init__(self) -> None:
        """空のfetch記録でuse case fakeを初期化する."""
        self.calls = []

    async def execute(self, target: BeatmapFetchTarget) -> None:
        """Task adapterが渡したfetch targetを記録する.

        Args:
            target (BeatmapFetchTarget): fetch対象を表すcommand input.

        Returns:
            None: targetを記録して完了し,呼び出し側へ値を返さない.
        """
        self.calls.append(target)


def _make_config(
    tmp_path: Path,
    *,
    beatmap_official_sources_enabled: bool = False,
    beatmap_metadata_mirror_base_urls: list[str] | None = None,
) -> AppConfig:
    """Worker startupをin-memoryで実行する最小AppConfigを生成する.

    Args:
        tmp_path (Path): logとblob storageを隔離するtest専用directory.
        beatmap_official_sources_enabled (bool): 公式metadata sourceを有効にするか.
        beatmap_metadata_mirror_base_urls (list[str] | None): metadata mirror URL一覧.

    Returns:
        AppConfig: test environmentとlocal storage pathを持つ設定値.
    """
    return AppConfig.model_validate(
        {
            "database_url": "postgresql://test:test@localhost:5432/test",
            "valkey_url": "redis://localhost:6379/0",
            "environment": "test",
            "log_dir": str(tmp_path),
            "blob_storage_local_root": str(tmp_path / "blobs"),
            "beatmap_official_sources_enabled": beatmap_official_sources_enabled,
            "beatmap_official_api_client_id": "test-client-id",
            "beatmap_official_api_client_secret": "test-client-secret",
            "beatmap_metadata_mirror_base_urls": beatmap_metadata_mirror_base_urls or [],
        }
    )


def _install_in_memory_worker_container(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    config: AppConfig,
    extra_overrides: tuple[Provider, ...] = (),
) -> None:
    """Worker moduleへin-memory Dishka container factoryを接続する.

    Args:
        monkeypatch (pytest.MonkeyPatch): worker moduleの設定とfactoryを置換するfixture.
        tmp_path (Path): in-memory blob storageのrootに使うtest専用directory.
        config (AppConfig): worker startupに渡すtest設定.
        extra_overrides (tuple[Provider, ...]): test個別に追加するDishka provider override.

    Returns:
        None: module依存を差し替えて完了し,呼び出し側へ値を返さない.
    """

    def make_test_worker_container(app_config: AppConfig) -> AsyncContainer:
        """Test runtime providerを持つworker containerを生成する.

        Args:
            app_config (AppConfig): worker moduleが読み込んだ設定値.

        Returns:
            AsyncContainer: in-memory provider overrideを含むworker container.
        """
        return make_worker_container(
            app_config,
            overrides=(
                make_in_memory_runtime_provider_set(
                    blob_root=tmp_path / "blobs",
                ),
                *extra_overrides,
            ),
        )

    monkeypatch.setattr(worker_module, "_config", config)
    monkeypatch.setattr(
        worker_module,
        "make_worker_container",
        make_test_worker_container,
    )


def _make_task_context(private_message_use_case: object) -> Context:
    """Private message taskを直接実行するTaskiq Contextを生成する.

    Args:
        private_message_use_case (object): broker stateへ設定するprivate persistence use case.

    Returns:
        Context: persist_private_messageが依存を取得できるtask context.
    """
    broker = InMemoryBroker()
    broker.state.persist_private_message_use_case = private_message_use_case
    message = TaskiqMessage(
        task_id="worker-test-id",
        task_name="persist_private_message",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


def _make_osu_direct_task_context(state: TaskiqState) -> Context:
    """Worker startup済みstateからosu!direct task用Contextを生成する.

    Args:
        state (TaskiqState): osu!direct use-caseを保持するworker lifecycle state.

    Returns:
        Context: osu!direct job adapterがruntime dependencyを取得できるtask context.
    """
    broker = InMemoryBroker()
    broker.state.osu_direct_feed_sync = _state_osu_direct_feed_sync(state)
    broker.state.osu_direct_range_crawl = _state_osu_direct_range_crawl(state)
    broker.state.osu_direct_indexing_commands = _state_osu_direct_indexing_commands(state)
    message = TaskiqMessage(
        task_id="worker-osu-direct-test-id",
        task_name="osu_direct_worker_test",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


def _state_dishka_container(state: TaskiqState) -> AsyncContainer | None:
    """Taskiq stateからDishka containerを型付きで取得する.

    Args:
        state (TaskiqState): worker lifecycleが更新するbroker state.

    Returns:
        AsyncContainer | None: 現在のcontainer. startup前またはshutdown後はNone.
    """
    return cast("AsyncContainer | None", getattr(state, "dishka_container", None))


def _state_persist_channel_message_use_case(state: TaskiqState) -> object | None:
    """Taskiq stateからchannel message persistence use caseを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みchannel persistence use case. 未設定時はNone.
    """
    return cast("object | None", getattr(state, "persist_channel_message_use_case", None))


def _state_persist_private_message_use_case(state: TaskiqState) -> object | None:
    """Taskiq stateからprivate message persistence use caseを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みprivate persistence use case. 未設定時はNone.
    """
    return cast("object | None", getattr(state, "persist_private_message_use_case", None))


def _state_beatmap_metadata_fetch(state: TaskiqState) -> object | None:
    """Taskiq stateからbeatmap metadata fetch use caseを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みmetadata fetch use case. 未設定時はNone.
    """
    return cast("object | None", getattr(state, "beatmap_metadata_fetch", None))


def _state_beatmap_file_fetch(state: TaskiqState) -> object | None:
    """Taskiq stateからbeatmap file fetch use caseを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みfile fetch use case. 未設定時はNone.
    """
    return cast("object | None", getattr(state, "beatmap_file_fetch", None))


def _state_score_performance_calculation_executor(state: TaskiqState) -> object | None:
    """Taskiq stateからscore performance calculation executorを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みperformance calculation executor. 未設定時はNone.
    """
    return cast("object | None", getattr(state, "score_performance_calculation_executor", None))


def _state_performance_recalculation_batch_processor(state: TaskiqState) -> object | None:
    """Taskiq stateからperformance recalculation batch processorを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みbatch processor. 未設定時はNone.
    """
    return cast("object | None", getattr(state, "performance_recalculation_batch_processor", None))


def _state_beatmap_leaderboard_user_rebuild_use_case(state: TaskiqState) -> object | None:
    """Taskiq stateからuser leaderboard rebuild use caseを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みuser leaderboard rebuild use case. 未設定時はNone.
    """
    return cast("object | None", getattr(state, "beatmap_leaderboard_user_rebuild_use_case", None))


def _state_beatmap_leaderboard_beatmapset_rebuild_use_case(
    state: TaskiqState,
) -> object | None:
    """Taskiq stateからbeatmapset leaderboard rebuild use caseを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みbeatmapset leaderboard rebuild use case. 未設定時はNone.
    """
    return cast(
        "object | None",
        getattr(state, "beatmap_leaderboard_beatmapset_rebuild_use_case", None),
    )


def _state_replay_download_accounting_executor(state: TaskiqState) -> object | None:
    """Taskiq stateからreplay download accounting executorを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みreplay download accounting executor. 未設定時はNone.
    """
    return cast("object | None", getattr(state, "replay_download_accounting_executor", None))


def _state_osu_direct_feed_sync(state: TaskiqState) -> object | None:
    """Taskiq stateからosu!direct feed sync use caseを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みfeed sync use case. 未設定時はNone.
    """
    return cast("object | None", getattr(state, "osu_direct_feed_sync", None))


def _state_osu_direct_range_crawl(state: TaskiqState) -> object | None:
    """Taskiq stateからosu!direct range crawl use caseを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みrange crawl use case. 未設定時はNone.
    """
    return cast("object | None", getattr(state, "osu_direct_range_crawl", None))


def _state_osu_direct_indexing_commands(state: TaskiqState) -> object | None:
    """Taskiq stateからosu!direct indexing commandを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みindexing command. 未設定時はNone.
    """
    return cast("object | None", getattr(state, "osu_direct_indexing_commands", None))


def _state_osu_direct_catalog_scheduler(state: TaskiqState) -> object | None:
    """Taskiq stateからosu!direct catalog schedulerを取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        object | None: 解決済みcatalog scheduler. 未設定時はNone.
    """
    return cast("object | None", getattr(state, "osu_direct_catalog_scheduler", None))


def _state_osu_direct_point_lookup_request_count(state: TaskiqState) -> int | None:
    """Taskiq stateからpoint lookupの最大upstream request数を取得する.

    Args:
        state (TaskiqState): lifecycle dependencyを保持するbroker state.

    Returns:
        int | None: 設定済み最大request数. 未設定時はNone.
    """
    return cast("int | None", getattr(state, "osu_direct_point_lookup_request_count", None))


async def _run_startup(state: TaskiqState) -> None:
    """型付きstartup hookをTaskiq stateで実行する.

    Args:
        state (TaskiqState): startup hookへ渡すbroker state.

    Returns:
        None: lifecycle startupを完了し,呼び出し側へ値を返さない.
    """
    hook = cast("WorkerLifecycleHook", worker_module.startup)
    await hook(state)


async def _run_shutdown(state: TaskiqState) -> None:
    """型付きshutdown hookをTaskiq stateで実行する.

    Args:
        state (TaskiqState): shutdown hookへ渡すbroker state.

    Returns:
        None: lifecycle shutdownを完了し,呼び出し側へ値を返さない.
    """
    hook = cast("WorkerLifecycleHook", worker_module.shutdown)
    await hook(state)


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """test前後のglobal logging stateを隔離して復元する.

    Yields:
        None: test本体へ制御を渡し,終了後にhandlerとstructlog設定を復元する.
    """
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level

    yield

    for handler in root.handlers:
        if hasattr(handler, "close"):
            handler.close()
    for logger_name in ("uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(logger_name).handlers:
            if hasattr(handler, "close"):
                handler.close()
    root.handlers = original_handlers
    root.level = original_level
    structlog.reset_defaults()


@pytest.mark.asyncio
async def test_worker_startup_configures_logging(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Worker startupがmasking付きJSON loggingを設定する契約を検証する.

    in-memory worker containerでstartupとshutdownを実行してlog eventを書き込む.
    JSON logにeventが残りpasswordがmaskされることを確認する.

    Args:
        monkeypatch (pytest.MonkeyPatch): worker moduleのruntime dependencyを差し替えるfixture.
        tmp_path (Path): worker logを隔離するtest専用directory.

    Returns:
        None: log内容とsecret maskingを検証して完了し,呼び出し側へ値を返さない.
    """
    state = TaskiqState()
    config = _make_config(tmp_path)
    _install_in_memory_worker_container(monkeypatch, tmp_path=tmp_path, config=config)

    await _run_startup(state)
    await _run_shutdown(state)

    logger: structlog.stdlib.BoundLogger = structlog.get_logger()  # pyright: ignore[reportAny]
    logger.info("worker_test_event", password="my_secret_password")

    json_path = tmp_path / "latest.jsonl"
    content = json_path.read_text().strip()
    assert content != ""
    parsed = cast("dict[str, object]", json.loads(content.split("\n")[-1]))
    assert parsed["event"] == "worker_test_event"
    assert parsed["password"] == "***"
    assert parsed["runtime_role"] == "worker"


@pytest.mark.asyncio
async def test_worker_startup_sets_task_use_cases_from_dishka_container(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Worker startupが全task use caseをDishka stateへ設定する契約を検証する.

    in-memory providerでstartupを実行する.
    containerとchatとbeatmapとscore taskの各use caseが期待した具象型でstateへ入ることを確認する.

    Args:
        monkeypatch (pytest.MonkeyPatch): worker moduleのruntime dependencyを差し替えるfixture.
        tmp_path (Path): in-memory providerのstorageを隔離するtest専用directory.

    Returns:
        None: lifecycle stateの全dependencyを検証して完了し,呼び出し側へ値を返さない.
    """
    state = TaskiqState()
    config = _make_config(
        tmp_path,
        beatmap_metadata_mirror_base_urls=[
            "https://mirror-one.example.com",
            "https://mirror-two.example.com",
        ],
    )
    _install_in_memory_worker_container(monkeypatch, tmp_path=tmp_path, config=config)

    await _run_startup(state)
    try:
        assert _state_dishka_container(state) is not None
        assert isinstance(
            _state_persist_channel_message_use_case(state),
            PersistChannelMessageUseCase,
        )
        assert isinstance(
            _state_persist_private_message_use_case(state),
            PersistPrivateMessageUseCase,
        )
        assert isinstance(_state_beatmap_metadata_fetch(state), FetchBeatmapMetadataUseCase)
        assert isinstance(
            getattr(state, "beatmap_metadata_fetch_semaphore", None),
            asyncio.Semaphore,
        )
        assert isinstance(_state_beatmap_file_fetch(state), FetchBeatmapFileUseCase)
        assert isinstance(
            _state_score_performance_calculation_executor(state),
            ExecutePerformanceCalculationUseCase,
        )
        assert isinstance(
            _state_performance_recalculation_batch_processor(state),
            ProcessPerformanceRecalculationBatchUseCase,
        )
        assert isinstance(
            _state_beatmap_leaderboard_user_rebuild_use_case(state),
            RebuildBeatmapLeaderboardsForUserUseCase,
        )
        assert isinstance(
            _state_beatmap_leaderboard_beatmapset_rebuild_use_case(state),
            RebuildBeatmapLeaderboardsForBeatmapsetUseCase,
        )
        assert isinstance(
            _state_replay_download_accounting_executor(state),
            ReplayDownloadAccountingUseCase,
        )
        assert isinstance(_state_osu_direct_feed_sync(state), DirectFeedSync)
        assert isinstance(_state_osu_direct_range_crawl(state), DirectRangeCrawl)
        assert isinstance(_state_osu_direct_indexing_commands(state), DirectIndexingCommands)
        assert isinstance(_state_osu_direct_catalog_scheduler(state), DirectCatalogScheduler)
        assert _state_osu_direct_point_lookup_request_count(state) == 4
    finally:
        await _run_shutdown(state)


@pytest.mark.asyncio
async def test_worker_startup_failure_closes_dishka_container(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """startup中のdependency解決失敗がcontainerをcloseしてstateを空にする契約を検証する.

    file fetch解決で失敗するcontainer factoryを接続してstartupを実行する.
    RuntimeError後に全state fieldがNoneでcontainer closeが1回となることを確認する.

    Args:
        monkeypatch (pytest.MonkeyPatch): worker moduleのcontainer factoryを失敗fakeへ差し替える
            fixture.
        tmp_path (Path): failure pathでも有効なtest設定を作るdirectory.

    Returns:
        None: failure cleanupのstateとclose回数を検証して完了し,呼び出し側へ値を返さない.
    """
    state = TaskiqState()
    config = _make_config(tmp_path)
    failing_container = FailingWorkerContainer()

    def make_failing_worker_container(_: AppConfig) -> FailingWorkerContainer:
        """startup失敗を再現する既存container fakeを返す.

        Args:
            _ (AppConfig): worker moduleがfactoryへ渡すtest設定.

        Returns:
            FailingWorkerContainer: file fetch解決を拒否する共有container fake.
        """
        return failing_container

    monkeypatch.setattr(worker_module, "_config", config)
    monkeypatch.setattr(
        worker_module,
        "make_worker_container",
        make_failing_worker_container,
    )

    with pytest.raises(RuntimeError, match="beatmap file fetch unavailable"):
        await _run_startup(state)

    assert _state_dishka_container(state) is None
    assert _state_persist_channel_message_use_case(state) is None
    assert _state_persist_private_message_use_case(state) is None
    assert _state_beatmap_metadata_fetch(state) is None
    assert getattr(state, "beatmap_metadata_fetch_semaphore", None) is None
    assert _state_beatmap_file_fetch(state) is None
    assert _state_score_performance_calculation_executor(state) is None
    assert _state_performance_recalculation_batch_processor(state) is None
    assert _state_beatmap_leaderboard_user_rebuild_use_case(state) is None
    assert _state_beatmap_leaderboard_beatmapset_rebuild_use_case(state) is None
    assert _state_osu_direct_feed_sync(state) is None
    assert _state_osu_direct_range_crawl(state) is None
    assert _state_osu_direct_indexing_commands(state) is None
    assert _state_osu_direct_catalog_scheduler(state) is None
    assert _state_osu_direct_point_lookup_request_count(state) is None
    assert _state_replay_download_accounting_executor(state) is None
    assert failing_container.close_calls == 1


@pytest.mark.asyncio
async def test_worker_runtime_chat_use_case_executes_persistence_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Worker stateのchat use caseがqueue taskからmessageを永続化する契約を検証する.

    in-memory workerをstartupしてprivate message taskを直接実行する.
    container queryがsenderとtarget間の保存済みcontentを返すことを確認する.

    Args:
        monkeypatch (pytest.MonkeyPatch): worker moduleのruntime dependencyを差し替えるfixture.
        tmp_path (Path): in-memory storageを隔離するtest専用directory.

    Returns:
        None: queue adapter経由のmessage永続化を検証して完了し,呼び出し側へ値を返さない.
    """
    state = TaskiqState()
    config = _make_config(tmp_path)
    _install_in_memory_worker_container(monkeypatch, tmp_path=tmp_path, config=config)

    await _run_startup(state)
    try:
        private_message_use_case = _state_persist_private_message_use_case(state)
        assert private_message_use_case is not None
        await persist_private_message(
            sender_id=1,
            target_id=2,
            sender_name="sender",
            target_name="target",
            content="secret",
            context=_make_task_context(private_message_use_case),
        )

        container = _state_dishka_container(state)
        assert container is not None
        query = await container.get(ListPrivateMessagesQuery)
        result = await query.execute(
            ListPrivateMessagesQueryInput(user_id=1, peer_user_id=2, limit=10)
        )

        assert [message.content for message in result.messages] == ["secret"]
    finally:
        await _run_shutdown(state)


@pytest.mark.asyncio
async def test_worker_runtime_osu_direct_catalog_and_index_tasks_execute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Worker stateのosu!direct use caseがqueue taskから実行できる契約を検証する.

    in-memory workerをstartupし,公式feedだけをMockTransportで応答させる.
    catalog sync/crawlとindex rebuild/update taskがmissing runtimeで落ちないことを確認する.

    Args:
        monkeypatch (pytest.MonkeyPatch): worker moduleのruntime dependencyを差し替えるfixture.
        tmp_path (Path): in-memory storageを隔離するtest専用directory.

    Returns:
        None: direct catalog/index taskをworker state経由で実行して完了する.
    """
    request_count = 0
    search_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """公式OAuthとbeatmapset searchのmock responseを返す.

        Args:
            request (httpx.Request): MockTransport handlerへ渡されるHTTP request.

        Returns:
            httpx.Response: tokenまたは空feed response.
        """
        nonlocal request_count, search_requests
        request_count += 1
        if request_count == 1:
            return httpx.Response(
                200,
                json={"access_token": "mock-access-token", "expires_in": 3600},
                request=request,
            )
        search_requests += 1
        return httpx.Response(
            200,
            json={"beatmapsets": [], "cursor_string": None, "total": 0},
            request=request,
        )

    state = TaskiqState()
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = _make_config(tmp_path, beatmap_official_sources_enabled=True)
    _install_in_memory_worker_container(
        monkeypatch,
        tmp_path=tmp_path,
        config=config,
        extra_overrides=(TestProviderSet(replace_value(httpx.AsyncClient, http_client)),),
    )

    started = False
    try:
        await _run_startup(state)
        started = True
        context = _make_osu_direct_task_context(state)

        await sync_osu_direct_feed_window(
            source="official",
            status_scope="ranked",
            sort_key="ranked",
            window_key="1",
            context=context,
        )
        await crawl_osu_direct_id_range(
            source="mirror",
            status_scope="ranked",
            from_beatmapset_id=1,
            to_beatmapset_id=1,
            context=context,
        )
        await rebuild_osu_direct_search_projection(context=context)
        await rebuild_osu_direct_external_index(context=context)
        await update_osu_direct_external_index(beatmapset_id=1, context=context)

        assert search_requests == 1
    finally:
        if started:
            await _run_shutdown(state)
        await http_client.aclose()


@pytest.mark.asyncio
async def test_worker_shutdown_clears_runtime_state() -> None:
    """Worker shutdownが全runtime stateをclearしてcontainerをcloseする契約を検証する.

    全dependency fieldを持つTaskiq stateでshutdownを実行する.
    各fieldがNoneになりcontainer fakeのclose回数が1になることを確認する.

    Returns:
        None: state clearとcontainer cleanupを検証して完了し,呼び出し側へ値を返さない.
    """
    state = TaskiqState()
    dishka_container = FakeDishkaContainer()
    state.dishka_container = dishka_container
    state.persist_channel_message_use_case = object()
    state.persist_private_message_use_case = object()
    state.beatmap_metadata_fetch = object()
    state.beatmap_metadata_fetch_semaphore = object()
    state.beatmap_file_fetch = object()
    state.score_performance_calculation_executor = object()
    state.performance_recalculation_batch_processor = object()
    state.beatmap_leaderboard_user_rebuild_use_case = object()
    state.beatmap_leaderboard_beatmapset_rebuild_use_case = object()
    state.osu_direct_feed_sync = object()
    state.osu_direct_range_crawl = object()
    state.osu_direct_indexing_commands = object()
    state.osu_direct_catalog_scheduler = object()
    state.osu_direct_point_lookup_request_count = 4
    state.replay_download_accounting_executor = object()

    await _run_shutdown(state)

    assert _state_dishka_container(state) is None
    assert _state_persist_channel_message_use_case(state) is None
    assert _state_persist_private_message_use_case(state) is None
    assert _state_beatmap_metadata_fetch(state) is None
    assert getattr(state, "beatmap_metadata_fetch_semaphore", None) is None
    assert _state_beatmap_file_fetch(state) is None
    assert _state_score_performance_calculation_executor(state) is None
    assert _state_performance_recalculation_batch_processor(state) is None
    assert _state_beatmap_leaderboard_user_rebuild_use_case(state) is None
    assert _state_beatmap_leaderboard_beatmapset_rebuild_use_case(state) is None
    assert _state_osu_direct_feed_sync(state) is None
    assert _state_osu_direct_range_crawl(state) is None
    assert _state_osu_direct_indexing_commands(state) is None
    assert _state_osu_direct_catalog_scheduler(state) is None
    assert _state_osu_direct_point_lookup_request_count(state) is None
    assert _state_replay_download_accounting_executor(state) is None
    assert dishka_container.close_calls == 1
