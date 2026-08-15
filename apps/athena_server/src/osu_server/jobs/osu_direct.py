"""osu!direct catalog/index command use-caseを呼び出すTaskiq adapterを定義する."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, Never, Protocol, cast

import structlog
from taskiq import Context, TaskiqDepends

from osu_server.domain.beatmaps import (
    BeatmapFetchTarget,
    BeatmapMetadataSource,
    DirectCoverageStatusScope,
)
from osu_server.infrastructure.jobs.registry import jobs
from osu_server.jobs.beatmap_fetch import (
    get_beatmap_metadata_fetch,
    get_beatmap_metadata_fetch_semaphore,
    run_beatmap_metadata_fetch,
)
from osu_server.services.commands.beatmaps.direct_catalog_sync import (
    DirectFeedWindow,
    DirectRangeCrawlChunk,
)
from osu_server.shared.ports import (
    DirectCatalogScheduleOutcome,
    DirectCatalogScheduleResult,
    DirectCatalogWorkKind,
)

FETCH_OSU_DIRECT_POINT_LOOKUP_METADATA_TASK = "fetch_osu_direct_point_lookup_metadata"
UPDATE_OSU_DIRECT_EXTERNAL_INDEX_TASK = "update_osu_direct_external_index"
_MAX_POINT_LOOKUP_REQUEUES = 3
_POINT_LOOKUP_FAILURE_RETRY_SECONDS = 1

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from taskiq import TaskiqState

    from osu_server.services.commands.beatmaps.direct_indexing import (
        DirectExternalIndexRebuildResult,
        DirectExternalIndexUpdateResult,
        DirectSearchProjectionRebuildResult,
    )

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))


class WorkerDirectFeedSync(Protocol):
    """feed window同期jobが要求するuse-case境界を表す."""

    async def execute(self, window: DirectFeedWindow) -> object:
        """Feed window同期を実行する.

        Args:
            window (DirectFeedWindow): primitive payloadから構築したfeed window.

        Returns:
            object: scheduler結果. job adapterではpayload境界だけを扱う.
        """
        ...


class WorkerDirectRangeCrawl(Protocol):
    """id range crawl jobが要求するuse-case境界を表す."""

    async def execute(self, chunk: DirectRangeCrawlChunk) -> object:
        """ID range crawlを実行する.

        Args:
            chunk (DirectRangeCrawlChunk): primitive payloadから構築したcrawl chunk.

        Returns:
            object: scheduler結果. job adapterではpayload境界だけを扱う.
        """
        ...


class WorkerDirectCatalogScheduler(Protocol):
    """direct catalog workを共有upstream budgetで実行する境界を表す."""

    async def run(
        self,
        work_kind: DirectCatalogWorkKind,
        work: Callable[[], Awaitable[None]],
        *,
        request_count: int = 1,
    ) -> DirectCatalogScheduleResult:
        """指定kindのworkをscheduler経由で実行する.

        Args:
            work_kind (DirectCatalogWorkKind): 実行するdirect catalog work種別.
            work (Callable[[], Awaitable[None]]): budget取得後に実行する処理.
            request_count (int): workが消費しうるupstream request数.

        Returns:
            DirectCatalogScheduleResult: schedulerの実行結果.
        """
        ...


class WorkerDirectIndexingCommands(Protocol):
    """index同期とrebuild jobが要求するcommand境界を表す."""

    async def update_external_index(
        self,
        beatmapset_id: int,
    ) -> DirectExternalIndexUpdateResult:
        """Projection documentをexternal indexへ同期する.

        Args:
            beatmapset_id (int): 同期対象beatmapset ID.

        Returns:
            DirectExternalIndexUpdateResult: document単位の同期結果.
        """
        ...

    async def rebuild_search_projection(self) -> DirectSearchProjectionRebuildResult:
        """保存済みmetadataからsearch projectionを再構築する.

        Returns:
            DirectSearchProjectionRebuildResult: projection rebuild結果.
        """
        ...

    async def rebuild_external_index(self) -> DirectExternalIndexRebuildResult:
        """Projection document群からexternal index stateを再構築する.

        Returns:
            DirectExternalIndexRebuildResult: external index rebuild結果.
        """
        ...


class _EnqueueableTask(Protocol):
    """primitive payloadをenqueueできるTaskiq taskの最小境界を表す."""

    async def kiq(self, *args: object, **kwargs: object) -> object:
        """Primitive payload引数を持つtaskをenqueueする.

        Args:
            *args (object): taskに渡すpositional payload.
            **kwargs (object): taskに渡すkeyword payload.

        Returns:
            object: broker実装が返すenqueue結果.
        """
        ...


class _TaskBroker(Protocol):
    """stable task nameからTaskiq taskを検索する最小境界を表す."""

    def find_task(self, task_name: str) -> _EnqueueableTask | None:
        """Stable task nameで登録済みtaskを検索する.

        Args:
            task_name (str): Taskiq registryに登録されたstable task名.

        Returns:
            _EnqueueableTask | None: 対応するtaskまたは未登録時のNone.
        """
        ...


class TaskiqDirectExternalIndexUpdateWorkerWake:
    """external index updateの起動要求をTaskiq jobへ変換する.

    Attributes:
        _broker (_TaskBroker): taskの検索とenqueueを担うbroker.
    """

    _broker: _TaskBroker

    def __init__(self, broker: _TaskBroker) -> None:
        """Taskiq brokerを起動adapterに設定する.

        Args:
            broker (_TaskBroker): taskの検索とenqueueを担うbroker.
        """
        self._broker = broker

    async def wake_external_index_update(self, *, beatmapset_id: int, reason: str) -> None:
        """External index update taskをbeatmapset IDだけでenqueueする.

        Args:
            beatmapset_id (int): 更新対象beatmapset ID.
            reason (str): 更新を要求した理由. task payloadには含めずlogへ残す.

        Returns:
            None: `update_osu_direct_external_index` taskのenqueueを完了する.

        Raises:
            RuntimeError: 対応するtaskがbrokerに未登録の場合.
        """
        task = self._broker.find_task(UPDATE_OSU_DIRECT_EXTERNAL_INDEX_TASK)
        if task is None:
            logger.error(
                "osu_direct_external_index_update_task_not_registered",
                task_name=UPDATE_OSU_DIRECT_EXTERNAL_INDEX_TASK,
                beatmapset_id=beatmapset_id,
                reason=reason,
            )
            msg = "osu!direct external index update task is not registered"
            raise RuntimeError(msg)

        try:
            _ = await task.kiq(beatmapset_id)
        except Exception:
            logger.exception(
                "osu_direct_external_index_update_enqueue_failed",
                task_name=UPDATE_OSU_DIRECT_EXTERNAL_INDEX_TASK,
                beatmapset_id=beatmapset_id,
                reason=reason,
            )
            raise


def get_osu_direct_feed_sync(state: TaskiqState) -> WorkerDirectFeedSync | None:
    """Taskiq stateからosu!direct feed sync use-caseを返す.

    Args:
        state (TaskiqState): worker runtimeが保持するTaskiq state.

    Returns:
        WorkerDirectFeedSync | None: 登録済みuse-caseまたは未登録時のNone.
    """
    return cast("WorkerDirectFeedSync | None", getattr(state, "osu_direct_feed_sync", None))


def get_osu_direct_range_crawl(state: TaskiqState) -> WorkerDirectRangeCrawl | None:
    """Taskiq stateからosu!direct range crawl use-caseを返す.

    Args:
        state (TaskiqState): worker runtimeが保持するTaskiq state.

    Returns:
        WorkerDirectRangeCrawl | None: 登録済みuse-caseまたは未登録時のNone.
    """
    return cast("WorkerDirectRangeCrawl | None", getattr(state, "osu_direct_range_crawl", None))


def get_osu_direct_catalog_scheduler(state: TaskiqState) -> WorkerDirectCatalogScheduler | None:
    """Taskiq stateからosu!direct catalog schedulerを返す.

    Args:
        state (TaskiqState): worker runtimeが保持するTaskiq state.

    Returns:
        WorkerDirectCatalogScheduler | None: 登録済みschedulerまたは未登録時のNone.
    """
    return cast(
        "WorkerDirectCatalogScheduler | None",
        getattr(state, "osu_direct_catalog_scheduler", None),
    )


def get_osu_direct_point_lookup_request_count(state: TaskiqState) -> int | None:
    """Taskiq stateからpoint lookup 1件の最大upstream request数を返す.

    Args:
        state (TaskiqState): worker runtimeが保持するTaskiq state.

    Returns:
        int | None: 公式OAuth/APIとmirror fallbackを含む最大request数. 未登録ならNone.
    """
    return cast(
        "int | None",
        getattr(state, "osu_direct_point_lookup_request_count", None),
    )


def get_osu_direct_indexing_commands(state: TaskiqState) -> WorkerDirectIndexingCommands | None:
    """Taskiq stateからosu!direct indexing commandを返す.

    Args:
        state (TaskiqState): worker runtimeが保持するTaskiq state.

    Returns:
        WorkerDirectIndexingCommands | None: 登録済みcommandまたは未登録時のNone.
    """
    return cast(
        "WorkerDirectIndexingCommands | None",
        getattr(state, "osu_direct_indexing_commands", None),
    )


@jobs.register(task_name=FETCH_OSU_DIRECT_POINT_LOOKUP_METADATA_TASK)
async def fetch_osu_direct_point_lookup_metadata(
    target_type: str,
    target_key: str,
    context: Annotated[Context, TaskiqDepends()],
    *,
    force_refresh: bool = False,
) -> None:
    """Point lookup由来のmetadata fetchを共有budget経由で実行する.

    Args:
        target_type (str): metadata fetchのtarget種別を表すprimitive payload.
        target_key (str): target種別に対応するlookup key.
        context (Context): use-caseとschedulerを取得するTaskiq runtime context.
        force_refresh (bool): cache状態にかかわらずrefreshするか.

    Returns:
        None: scheduler結果を記録してmetadata fetch処理を完了する.

    Raises:
        RuntimeError: runtime dependency未登録,retry不可,または再投入上限到達の場合.
        NoResultError: retry可能な結果をTaskiqへ再投入した場合.
        ValueError: payloadがBeatmapFetchTargetの不変条件を満たさない場合.
    """
    use_case = get_beatmap_metadata_fetch(context.state)
    if use_case is None:
        _raise_runtime_missing(
            task_name=FETCH_OSU_DIRECT_POINT_LOOKUP_METADATA_TASK,
            dependency="beatmap_metadata_fetch",
        )
    scheduler = get_osu_direct_catalog_scheduler(context.state)
    if scheduler is None:
        _raise_runtime_missing(
            task_name=FETCH_OSU_DIRECT_POINT_LOOKUP_METADATA_TASK,
            dependency="osu_direct_catalog_scheduler",
        )
    request_count = get_osu_direct_point_lookup_request_count(context.state)
    if request_count is None:
        _raise_runtime_missing(
            task_name=FETCH_OSU_DIRECT_POINT_LOOKUP_METADATA_TASK,
            dependency="osu_direct_point_lookup_request_count",
        )
    target = BeatmapFetchTarget.from_queue_payload(
        target_type=target_type,
        target_key=target_key,
        force_refresh=force_refresh,
    )
    semaphore = get_beatmap_metadata_fetch_semaphore(context.state)

    async def work() -> None:
        """Metadata fetch use-caseをscheduler内で実行する.

        Returns:
            None: use-caseへtargetを渡して完了する.
        """
        await run_beatmap_metadata_fetch(use_case, target, semaphore)

    result = await scheduler.run(
        DirectCatalogWorkKind.POINT_LOOKUP,
        work,
        request_count=request_count,
    )
    if result.outcome is DirectCatalogScheduleOutcome.COMPLETED:
        return

    raw_requeue_count = cast(
        "object",
        context.message.labels.get("X-Taskiq-requeue", "0"),
    )
    requeue_count = int(raw_requeue_count) if isinstance(raw_requeue_count, (int, str)) else 0
    logger.warning(
        "osu_direct_point_lookup_not_completed",
        outcome=result.outcome.value,
        retry_eligible=result.retry_eligible,
        retry_after_seconds=result.retry_after_seconds,
        failure_reason=result.failure_reason,
        requeue_count=requeue_count,
        target_type=target_type,
        target_key=target_key,
    )
    if not result.retry_eligible or requeue_count >= _MAX_POINT_LOOKUP_REQUEUES:
        msg = result.failure_reason or "osu!direct point lookup metadata fetch failed"
        raise RuntimeError(msg)

    retry_after_seconds = (
        result.retry_after_seconds
        if result.retry_after_seconds is not None
        else _POINT_LOOKUP_FAILURE_RETRY_SECONDS
    )
    await asyncio.sleep(retry_after_seconds)
    await context.requeue()


@jobs.register(task_name="sync_osu_direct_feed_window")
async def sync_osu_direct_feed_window(
    source: object,
    status_scope: object,
    sort_key: object,
    window_key: object,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Feed window payloadを検証してcatalog sync use-caseへ委譲する.

    Args:
        source (object): `BeatmapMetadataSource`のwire値.
        status_scope (object): `DirectCoverageStatusScope`のwire値.
        sort_key (object): feed sortの識別子.
        window_key (object): page, cursor,またはwindowの識別子.
        context (Context): use-caseを取得するTaskiq runtime context.

    Returns:
        None: feed sync use-caseへ委譲して完了する.

    Raises:
        RuntimeError: feed sync use-caseがworker stateに未登録の場合.
        ValueError: payloadがfeed windowの制約を満たさない場合.
    """
    window = DirectFeedWindow(
        source=_validate_metadata_source(source),
        status_scope=_validate_status_scope(status_scope),
        sort_key=_validate_non_empty_str(sort_key, "sort_key"),
        window_key=_validate_non_empty_str(window_key, "window_key"),
    )
    use_case = get_osu_direct_feed_sync(context.state)
    if use_case is None:
        _raise_runtime_missing(
            task_name="sync_osu_direct_feed_window",
            dependency="osu_direct_feed_sync",
        )
    _ = await use_case.execute(window)


@jobs.register(task_name="crawl_osu_direct_id_range")
async def crawl_osu_direct_id_range(
    source: object,
    status_scope: object,
    from_beatmapset_id: object,
    to_beatmapset_id: object,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """ID range payloadを検証してcatalog crawl use-caseへ委譲する.

    Args:
        source (object): `BeatmapMetadataSource`のwire値.
        status_scope (object): `DirectCoverageStatusScope`のwire値.
        from_beatmapset_id (object): crawl対象rangeの開始ID.
        to_beatmapset_id (object): crawl対象rangeの終了ID.
        context (Context): use-caseを取得するTaskiq runtime context.

    Returns:
        None: range crawl use-caseへ委譲して完了する.

    Raises:
        RuntimeError: range crawl use-caseがworker stateに未登録の場合.
        ValueError: payloadがrange chunkの制約を満たさない場合.
    """
    chunk = DirectRangeCrawlChunk(
        source=_validate_metadata_source(source),
        status_scope=_validate_status_scope(status_scope),
        from_beatmapset_id=_validate_non_negative_int(
            from_beatmapset_id,
            "from_beatmapset_id",
        ),
        to_beatmapset_id=_validate_non_negative_int(
            to_beatmapset_id,
            "to_beatmapset_id",
        ),
    )
    use_case = get_osu_direct_range_crawl(context.state)
    if use_case is None:
        _raise_runtime_missing(
            task_name="crawl_osu_direct_id_range",
            dependency="osu_direct_range_crawl",
        )
    _ = await use_case.execute(chunk)


@jobs.register(task_name=UPDATE_OSU_DIRECT_EXTERNAL_INDEX_TASK)
async def update_osu_direct_external_index(
    beatmapset_id: object,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """External index update payloadを検証してindexing commandへ委譲する.

    Args:
        beatmapset_id (object): external indexへ同期するbeatmapset ID.
        context (Context): commandを取得するTaskiq runtime context.

    Returns:
        None: indexing commandへ委譲して完了する.

    Raises:
        RuntimeError: indexing commandがworker stateに未登録の場合.
        ValueError: beatmapset_idが正の整数でない場合.
    """
    validated_beatmapset_id = _validate_positive_int(beatmapset_id, "beatmapset_id")
    use_case = get_osu_direct_indexing_commands(context.state)
    if use_case is None:
        _raise_runtime_missing(
            task_name="update_osu_direct_external_index",
            dependency="osu_direct_indexing_commands",
        )
    _ = await use_case.update_external_index(validated_beatmapset_id)


@jobs.register(task_name="rebuild_osu_direct_search_projection")
async def rebuild_osu_direct_search_projection(
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Search projection rebuildをindexing commandへ委譲する.

    Args:
        context (Context): commandを取得するTaskiq runtime context.

    Returns:
        None: projection rebuild commandへ委譲して完了する.

    Raises:
        RuntimeError: indexing commandがworker stateに未登録の場合.
    """
    use_case = get_osu_direct_indexing_commands(context.state)
    if use_case is None:
        _raise_runtime_missing(
            task_name="rebuild_osu_direct_search_projection",
            dependency="osu_direct_indexing_commands",
        )
    _ = await use_case.rebuild_search_projection()


@jobs.register(task_name="rebuild_osu_direct_external_index")
async def rebuild_osu_direct_external_index(
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """External index rebuildをindexing commandへ委譲する.

    Args:
        context (Context): commandを取得するTaskiq runtime context.

    Returns:
        None: external index rebuild commandへ委譲して完了する.

    Raises:
        RuntimeError: indexing commandがworker stateに未登録の場合.
    """
    use_case = get_osu_direct_indexing_commands(context.state)
    if use_case is None:
        _raise_runtime_missing(
            task_name="rebuild_osu_direct_external_index",
            dependency="osu_direct_indexing_commands",
        )
    _ = await use_case.rebuild_external_index()


def _validate_metadata_source(value: object) -> BeatmapMetadataSource:
    """Payload値をBeatmapMetadataSourceへ変換する.

    Args:
        value (object): task payloadのmetadata source値.

    Returns:
        BeatmapMetadataSource: 検証済みsource.

    Raises:
        ValueError: valueが既知のmetadata sourceでない場合.
    """
    if not isinstance(value, str):
        msg = "source must be a valid beatmap metadata source"
        raise TypeError(msg)
    try:
        return BeatmapMetadataSource(value)
    except ValueError as exc:
        msg = "source must be a valid beatmap metadata source"
        raise ValueError(msg) from exc


def _validate_status_scope(value: object) -> DirectCoverageStatusScope:
    """Payload値をDirectCoverageStatusScopeへ変換する.

    Args:
        value (object): task payloadのcoverage status scope値.

    Returns:
        DirectCoverageStatusScope: 検証済みstatus scope.

    Raises:
        ValueError: valueが既知のstatus scopeでない場合.
    """
    if not isinstance(value, str):
        msg = "status_scope must be a valid direct coverage status scope"
        raise TypeError(msg)
    try:
        return DirectCoverageStatusScope(value)
    except ValueError as exc:
        msg = "status_scope must be a valid direct coverage status scope"
        raise ValueError(msg) from exc


def _validate_non_empty_str(value: object, field_name: str) -> str:
    """Payload値が空でない文字列か検証する.

    Args:
        value (object): 検証するpayload値.
        field_name (str): error messageへ入れるfield名.

    Returns:
        str: 検証済み文字列.

    Raises:
        ValueError: valueが文字列でないか空の場合.
    """
    if not isinstance(value, str) or not value:
        msg = f"{field_name} must be a non-empty string"
        raise ValueError(msg)
    return value


def _validate_positive_int(value: object, field_name: str) -> int:
    """Payload値がboolでない正の整数か検証する.

    Args:
        value (object): 検証するpayload値.
        field_name (str): error messageへ入れるfield名.

    Returns:
        int: 検証済みの正の整数.

    Raises:
        ValueError: valueが正の整数でない場合.
    """
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        msg = f"{field_name} must be a positive integer"
        raise ValueError(msg)
    return value


def _validate_non_negative_int(value: object, field_name: str) -> int:
    """Payload値がboolでない0以上の整数か検証する.

    Args:
        value (object): 検証するpayload値.
        field_name (str): error messageへ入れるfield名.

    Returns:
        int: 検証済みの0以上の整数.

    Raises:
        ValueError: valueが0以上の整数でない場合.
    """
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        msg = f"{field_name} must be a non-negative integer"
        raise ValueError(msg)
    return value


def _raise_runtime_missing(*, task_name: str, dependency: str) -> Never:
    """未登録runtime dependencyを構造化logへ出してRuntimeErrorにする.

    Args:
        task_name (str): 失敗したTaskiq task名.
        dependency (str): Taskiq stateで期待したdependency名.

    Returns:
        None: 常にRuntimeErrorを送出するため返らない.

    Raises:
        RuntimeError: 指定dependencyがworker stateに未登録の場合.
    """
    logger.error(
        "osu_direct_job_runtime_missing",
        task_name=task_name,
        dependency=dependency,
    )
    dependency_name = dependency.replace("osu_direct", "osu!direct").replace("_", " ")
    msg = f"{dependency_name} use-case is not registered"
    raise RuntimeError(msg)


__all__ = [
    "FETCH_OSU_DIRECT_POINT_LOOKUP_METADATA_TASK",
    "UPDATE_OSU_DIRECT_EXTERNAL_INDEX_TASK",
    "TaskiqDirectExternalIndexUpdateWorkerWake",
    "WorkerDirectCatalogScheduler",
    "WorkerDirectFeedSync",
    "WorkerDirectIndexingCommands",
    "WorkerDirectRangeCrawl",
    "crawl_osu_direct_id_range",
    "fetch_osu_direct_point_lookup_metadata",
    "get_osu_direct_catalog_scheduler",
    "get_osu_direct_feed_sync",
    "get_osu_direct_indexing_commands",
    "get_osu_direct_point_lookup_request_count",
    "get_osu_direct_range_crawl",
    "rebuild_osu_direct_external_index",
    "rebuild_osu_direct_search_projection",
    "sync_osu_direct_feed_window",
    "update_osu_direct_external_index",
]
