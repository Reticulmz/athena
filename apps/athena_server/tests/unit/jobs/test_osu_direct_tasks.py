"""osu!direct Taskiq adapterのprimitive payload境界を検証する."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest
import structlog.testing
from taskiq import Context, InMemoryBroker, TaskiqMessage

from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    DirectCoverageStatusScope,
)
from osu_server.infrastructure.jobs.registry import jobs
from osu_server.jobs import osu_direct, register_all_jobs
from osu_server.jobs.osu_direct import (
    TaskiqDirectExternalIndexUpdateWorkerWake,
    crawl_osu_direct_id_range,
    get_osu_direct_feed_sync,
    get_osu_direct_indexing_commands,
    get_osu_direct_range_crawl,
    rebuild_osu_direct_external_index,
    rebuild_osu_direct_search_projection,
    sync_osu_direct_feed_window,
    update_osu_direct_external_index,
)
from osu_server.services.commands.beatmaps.direct_indexing import (
    DirectExternalIndexRebuildResult,
    DirectExternalIndexUpdateOutcome,
    DirectExternalIndexUpdateResult,
    DirectSearchProjectionRebuildResult,
)

if TYPE_CHECKING:
    from osu_server.services.commands.beatmaps.direct_catalog_sync import (
        DirectFeedWindow,
        DirectRangeCrawlChunk,
    )


class _FakeFeedSync:
    """feed sync taskから渡されたwindowを記録するtest double.

    Attributes:
        calls (list[DirectFeedWindow]): executeへ渡されたwindow履歴.
    """

    calls: list[DirectFeedWindow]

    def __init__(self) -> None:
        """空の呼び出し履歴でtest doubleを初期化する."""
        self.calls = []

    async def execute(self, window: DirectFeedWindow) -> object:
        """Adapterが構築したwindowを記録する.

        Args:
            window (object): adapterがprimitive payloadから作ったwindow.

        Returns:
            object: command resultをこのtestでは検証しないため新規objectを返す.
        """
        self.calls.append(window)
        return object()


class _FakeRangeCrawl:
    """id range crawl taskから渡されたchunkを記録するtest double.

    Attributes:
        calls (list[DirectRangeCrawlChunk]): executeへ渡されたchunk履歴.
    """

    calls: list[DirectRangeCrawlChunk]

    def __init__(self) -> None:
        """空の呼び出し履歴でtest doubleを初期化する."""
        self.calls = []

    async def execute(self, chunk: DirectRangeCrawlChunk) -> object:
        """Adapterが構築したchunkを記録する.

        Args:
            chunk (object): adapterがprimitive payloadから作ったchunk.

        Returns:
            object: command resultをこのtestでは検証しないため新規objectを返す.
        """
        self.calls.append(chunk)
        return object()


class _FakeIndexingCommands:
    """direct indexing taskの各command呼び出しを記録するtest double.

    Attributes:
        update_calls (list[int]): update_external_indexへ渡されたbeatmapset ID履歴.
        projection_rebuild_calls (int): projection rebuild呼び出し回数.
        external_rebuild_calls (int): external index rebuild呼び出し回数.
    """

    update_calls: list[int]
    projection_rebuild_calls: int
    external_rebuild_calls: int

    def __init__(self) -> None:
        """空の呼び出し履歴でindexing command doubleを初期化する."""
        self.update_calls = []
        self.projection_rebuild_calls = 0
        self.external_rebuild_calls = 0

    async def update_external_index(self, beatmapset_id: int) -> DirectExternalIndexUpdateResult:
        """External index update対象IDを記録する.

        Args:
            beatmapset_id (int): adapterが検証したbeatmapset ID.

        Returns:
            DirectExternalIndexUpdateResult: 成功扱いの固定結果.
        """
        self.update_calls.append(beatmapset_id)
        return DirectExternalIndexUpdateResult(outcome=DirectExternalIndexUpdateOutcome.SUCCEEDED)

    async def rebuild_search_projection(self) -> DirectSearchProjectionRebuildResult:
        """Projection rebuild呼び出しを記録する.

        Returns:
            DirectSearchProjectionRebuildResult: 0件処理の固定結果.
        """
        self.projection_rebuild_calls += 1
        return DirectSearchProjectionRebuildResult(rebuilt_count=0)

    async def rebuild_external_index(self) -> DirectExternalIndexRebuildResult:
        """External index rebuild呼び出しを記録する.

        Returns:
            DirectExternalIndexRebuildResult: 0件処理の固定結果.
        """
        self.external_rebuild_calls += 1
        return DirectExternalIndexRebuildResult(succeeded_count=0, failed_count=0)


class _FakeEnqueueableTask:
    """worker wakeがenqueueするpayloadと失敗を再現するtask double.

    Attributes:
        _error (Exception | None): kiqで送出する例外. Noneならenqueue成功を返す.
        calls (list[tuple[tuple[object, ...], dict[str, object]]]): kiqへ渡されたpayload履歴.
    """

    _error: Exception | None

    def __init__(self, *, error: Exception | None = None) -> None:
        """enqueue失敗の有無と空のpayload履歴を設定する.

        Args:
            error (Exception | None): kiqで送出する例外. Noneなら正常に完了する.
        """
        self._error = error
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def kiq(self, *args: object, **kwargs: object) -> object:
        """payloadを記録して成功objectを返すか,設定済み例外を送出する.

        Args:
            *args (object): taskへ渡される位置引数payload.
            **kwargs (object): taskへ渡される名前付きpayload.

        Returns:
            object: enqueue成功を表す新しいobject.
        """
        self.calls.append((args, kwargs))
        if self._error is not None:
            raise self._error
        return object()


class _FakeBroker:
    """指定taskを返し,worker wakeのtask lookupを記録するbroker double.

    Attributes:
        _task (_FakeEnqueueableTask | None): lookup時に返すtask. Noneは未登録を表す.
        task_names (list[str]): find_taskへ渡されたtask名の履歴.
    """

    _task: _FakeEnqueueableTask | None

    def __init__(self, task: _FakeEnqueueableTask | None) -> None:
        """lookup結果に使うtask doubleを初期化する.

        Args:
            task (_FakeEnqueueableTask | None): 返すtask. Noneなら未登録状態を再現する.
        """
        self._task = task
        self.task_names: list[str] = []

    def find_task(self, task_name: str) -> _FakeEnqueueableTask | None:
        """task名を記録して設定済みtaskを返す.

        Args:
            task_name (str): worker wakeが解決を試みるtask名.

        Returns:
            _FakeEnqueueableTask | None: 設定済みtask,または未登録を表すNone.
        """
        self.task_names.append(task_name)
        return self._task


def _make_context(**services: object) -> Context:
    """指定serviceをTaskiq stateへ登録したtest用contextを構築する.

    Args:
        **services (object): state属性名と登録するtest doubleの対応.

    Returns:
        Context: osu!direct taskを直接実行できるTaskiq context.
    """
    broker = InMemoryBroker()
    for key, value in services.items():
        object.__setattr__(broker.state, key, value)
    message = TaskiqMessage(
        task_id="osu-direct-test-task",
        task_name="test",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


def test_osu_direct_tasks_are_registered() -> None:
    """osu!direct worker task名がregistryへ登録されることを検証する.

    Returns:
        None: 各task名がregistryに存在することを確認して完了する.
    """
    assert "sync_osu_direct_feed_window" in jobs.task_names
    assert "crawl_osu_direct_id_range" in jobs.task_names
    assert "update_osu_direct_external_index" in jobs.task_names
    assert "rebuild_osu_direct_search_projection" in jobs.task_names
    assert "rebuild_osu_direct_external_index" in jobs.task_names


def test_register_all_jobs_attaches_osu_direct_tasks_to_broker() -> None:
    """register_all_jobsがosu!direct taskをbrokerへ接続することを検証する.

    Returns:
        None: in-memory brokerから各taskを発見できることを確認して完了する.
    """
    broker = InMemoryBroker()

    register_all_jobs(broker)

    assert broker.find_task("sync_osu_direct_feed_window") is not None
    assert broker.find_task("crawl_osu_direct_id_range") is not None
    assert broker.find_task("update_osu_direct_external_index") is not None
    assert broker.find_task("rebuild_osu_direct_search_projection") is not None
    assert broker.find_task("rebuild_osu_direct_external_index") is not None


def test_osu_direct_jobs_stay_queue_adapters_only() -> None:
    """osu!direct job adapterがrepositoryやSQLAlchemyを所有しないことを検証する.

    Returns:
        None: sourceにSQLAlchemyやrepository importがないことを確認して完了する.
    """
    source = inspect.getsource(osu_direct)

    assert "sqlalchemy" not in source
    assert "osu_server.repositories" not in source


async def test_feed_sync_raises_when_runtime_missing() -> None:
    """Feed sync use-case未登録時にRuntimeErrorとerror logを残すことを検証する.

    Returns:
        None: missing runtimeがobservable failureになることを確認して完了する.
    """
    context = _make_context()

    with (
        structlog.testing.capture_logs() as logs,
        pytest.raises(RuntimeError, match="osu!direct feed sync use-case is not registered"),
    ):
        await sync_osu_direct_feed_window(
            source="mirror",
            status_scope="ranked",
            sort_key="newest",
            window_key="1",
            context=context,
        )

    entries = [entry for entry in logs if entry.get("event") == "osu_direct_job_runtime_missing"]
    assert len(entries) == 1
    assert entries[0]["task_name"] == "sync_osu_direct_feed_window"
    assert entries[0]["dependency"] == "osu_direct_feed_sync"
    assert entries[0]["log_level"] == "error"


async def test_feed_sync_delegates_valid_payload() -> None:
    """Feed sync payloadをDirectFeedWindowへ変換してuse-caseへ委譲する.

    Returns:
        None: 変換後windowの値がprimitive payloadと一致することを確認する.
    """
    fake = _FakeFeedSync()
    context = _make_context(osu_direct_feed_sync=fake)

    await sync_osu_direct_feed_window(
        source="mirror",
        status_scope="ranked",
        sort_key="newest",
        window_key="1",
        context=context,
    )

    assert len(fake.calls) == 1
    window = fake.calls[0]
    assert window.source is BeatmapMetadataSource.MIRROR
    assert window.status_scope is DirectCoverageStatusScope.RANKED
    assert window.sort_key == "newest"
    assert window.window_key == "1"


async def test_feed_sync_rejects_invalid_source_before_use_case() -> None:
    """不正source payloadをuse-case実行前に拒否することを検証する.

    Returns:
        None: ValueError後にuse-caseが呼ばれていないことを確認する.
    """
    fake = _FakeFeedSync()
    context = _make_context(osu_direct_feed_sync=fake)

    with pytest.raises(ValueError, match="source must be a valid beatmap metadata source"):
        await sync_osu_direct_feed_window(
            source="unknown-source",
            status_scope="ranked",
            sort_key="newest",
            window_key="1",
            context=context,
        )

    assert fake.calls == []


async def test_range_crawl_delegates_valid_payload() -> None:
    """Id range payloadをDirectRangeCrawlChunkへ変換してuse-caseへ委譲する.

    Returns:
        None: 変換後chunkの値がprimitive payloadと一致することを確認する.
    """
    fake = _FakeRangeCrawl()
    context = _make_context(osu_direct_range_crawl=fake)

    await crawl_osu_direct_id_range(
        source="mirror",
        status_scope="ranked",
        from_beatmapset_id=1000,
        to_beatmapset_id=1010,
        context=context,
    )

    assert len(fake.calls) == 1
    chunk = fake.calls[0]
    assert chunk.source is BeatmapMetadataSource.MIRROR
    assert chunk.status_scope is DirectCoverageStatusScope.RANKED
    assert chunk.from_beatmapset_id == 1000
    assert chunk.to_beatmapset_id == 1010


async def test_range_crawl_rejects_bool_id_before_use_case() -> None:
    """boolのrange ID payloadをuse-case実行前に拒否することを検証する.

    Returns:
        None: ValueError後にuse-caseが呼ばれていないことを確認する.
    """
    fake = _FakeRangeCrawl()
    context = _make_context(osu_direct_range_crawl=fake)

    with pytest.raises(ValueError, match="from_beatmapset_id must be a non-negative integer"):
        await crawl_osu_direct_id_range(
            source="mirror",
            status_scope="ranked",
            from_beatmapset_id=True,
            to_beatmapset_id=1010,
            context=context,
        )

    assert fake.calls == []


async def test_external_index_update_delegates_positive_id() -> None:
    """External index update payloadを正のIDとして検証しuse-caseへ委譲する.

    Returns:
        None: use-caseが検証済みbeatmapset IDで1回呼ばれることを確認する.
    """
    fake = _FakeIndexingCommands()
    context = _make_context(osu_direct_indexing_commands=fake)

    await update_osu_direct_external_index(beatmapset_id=1000, context=context)

    assert fake.update_calls == [1000]


async def test_external_index_update_rejects_zero_id_before_use_case() -> None:
    """0のbeatmapset IDをuse-case実行前に拒否することを検証する.

    Returns:
        None: ValueError後にindexing commandが呼ばれていないことを確認する.
    """
    fake = _FakeIndexingCommands()
    context = _make_context(osu_direct_indexing_commands=fake)

    with pytest.raises(ValueError, match="beatmapset_id must be a positive integer"):
        await update_osu_direct_external_index(beatmapset_id=0, context=context)

    assert fake.update_calls == []


async def test_rebuild_tasks_delegate_to_indexing_commands() -> None:
    """rebuild系taskがindexing commandの対応methodへ委譲することを検証する.

    Returns:
        None: projection rebuildとexternal rebuildが1回ずつ実行されることを確認する.
    """
    fake = _FakeIndexingCommands()
    context = _make_context(osu_direct_indexing_commands=fake)

    await rebuild_osu_direct_search_projection(context=context)
    await rebuild_osu_direct_external_index(context=context)

    assert fake.projection_rebuild_calls == 1
    assert fake.external_rebuild_calls == 1


async def test_direct_external_index_update_worker_wake_enqueues_primitive_payload() -> None:
    """External index update wakeがbeatmapset IDだけをtaskへenqueueすることを検証する.

    Returns:
        None: task lookupとpayload履歴が期待値と一致することを確認する.
    """
    task = _FakeEnqueueableTask()
    broker = _FakeBroker(task)
    wake = TaskiqDirectExternalIndexUpdateWorkerWake(broker)

    await wake.wake_external_index_update(
        beatmapset_id=1000,
        reason="beatmap_metadata_saved",
    )

    assert broker.task_names == ["update_osu_direct_external_index"]
    assert task.calls == [((1000,), {})]


async def test_direct_external_index_update_worker_wake_raises_when_task_missing() -> None:
    """External index update task未登録時にworker wakeがRuntimeErrorを送出する.

    Returns:
        None: 未登録taskを示すRuntimeErrorが送出されることを確認して完了する.
    """
    broker = _FakeBroker(None)
    wake = TaskiqDirectExternalIndexUpdateWorkerWake(broker)

    with pytest.raises(
        RuntimeError,
        match="osu!direct external index update task is not registered",
    ):
        await wake.wake_external_index_update(
            beatmapset_id=1000,
            reason="beatmap_metadata_saved",
        )


async def test_direct_external_index_update_worker_wake_surfaces_enqueue_failure() -> None:
    """External index update taskのenqueue失敗をworker wakeが伝播することを検証する.

    Returns:
        None: broker由来のRuntimeErrorが送出されることを確認して完了する.
    """
    task = _FakeEnqueueableTask(error=RuntimeError("broker unavailable"))
    broker = _FakeBroker(task)
    wake = TaskiqDirectExternalIndexUpdateWorkerWake(broker)

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await wake.wake_external_index_update(
            beatmapset_id=1000,
            reason="beatmap_metadata_saved",
        )


def test_state_helpers_return_registered_dependencies() -> None:
    """State helperがosu!direct用runtime dependencyだけを返すことを検証する.

    Returns:
        None: 各state keyの値がhelperから同一objectとして返ることを確認する.
    """
    feed = _FakeFeedSync()
    range_crawl = _FakeRangeCrawl()
    indexing = _FakeIndexingCommands()
    context = _make_context(
        osu_direct_feed_sync=feed,
        osu_direct_range_crawl=range_crawl,
        osu_direct_indexing_commands=indexing,
    )

    assert get_osu_direct_feed_sync(context.state) is feed
    assert get_osu_direct_range_crawl(context.state) is range_crawl
    assert get_osu_direct_indexing_commands(context.state) is indexing
