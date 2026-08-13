"""beatmap fetch command use-case を呼び出す Taskiq adapter を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol, cast

import structlog
from taskiq import Context, TaskiqDepends

from osu_server.domain.beatmaps import BeatmapFetchTarget
from osu_server.infrastructure.jobs.registry import jobs
from osu_server.shared.ports import DirectCatalogWorkKind

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable, Callable

    from taskiq import TaskiqState

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class WorkerBeatmapMetadataFetch(Protocol):
    """beatmap metadata fetch job が要求する use-case 境界を表す."""

    async def execute(self, target: BeatmapFetchTarget) -> None:
        """Metadata fetch target を処理する.

        Args:
            target (BeatmapFetchTarget): metadata を取得する typed target.

        Returns:
            None: metadata 取得処理を完了する.
        """
        ...


class WorkerBeatmapFileFetch(Protocol):
    """beatmap file fetch job が要求する use-case 境界を表す."""

    async def execute(self, target: BeatmapFetchTarget) -> None:
        """File fetch target を処理する.

        Args:
            target (BeatmapFetchTarget): file を取得する typed target.

        Returns:
            None: file 取得処理を完了する.
        """
        ...


class WorkerDirectCatalogScheduler(Protocol):
    """direct catalog workを共有upstream budgetで実行する境界を表す."""

    async def run(
        self,
        work_kind: DirectCatalogWorkKind,
        work: Callable[[], Awaitable[None]],
    ) -> object:
        """指定kindのworkをscheduler経由で実行する.

        Args:
            work_kind (DirectCatalogWorkKind): 実行するdirect catalog work種別.
            work (Callable[[], Awaitable[None]]): budget取得後に実行する処理.

        Returns:
            object: scheduler固有の実行結果. job adapterでは結果詳細を扱わない.
        """
        ...


def get_beatmap_metadata_fetch(state: TaskiqState) -> WorkerBeatmapMetadataFetch | None:
    """Taskiq state から beatmap metadata fetch use-case を返す.

    Args:
        state (TaskiqState): worker runtime が保持する Taskiq state.

    Returns:
        WorkerBeatmapMetadataFetch | None: 登録済み use-case または未登録時の None.
    """
    return cast(
        "WorkerBeatmapMetadataFetch | None",
        getattr(state, "beatmap_metadata_fetch", None),
    )


def get_beatmap_file_fetch(state: TaskiqState) -> WorkerBeatmapFileFetch | None:
    """Taskiq state から beatmap file fetch use-case を返す.

    Args:
        state (TaskiqState): worker runtime が保持する Taskiq state.

    Returns:
        WorkerBeatmapFileFetch | None: 登録済み use-case または未登録時の None.
    """
    return cast(
        "WorkerBeatmapFileFetch | None",
        getattr(state, "beatmap_file_fetch", None),
    )


def get_beatmap_metadata_fetch_semaphore(state: TaskiqState) -> asyncio.Semaphore | None:
    """Taskiq stateからmetadata fetch同時実行制限semaphoreを返す.

    Args:
        state (TaskiqState): worker runtimeが保持するTaskiq state.

    Returns:
        asyncio.Semaphore | None: 登録済みsemaphoreまたは未登録時のNone.
    """
    return cast(
        "asyncio.Semaphore | None",
        getattr(state, "beatmap_metadata_fetch_semaphore", None),
    )


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


async def _run_metadata_fetch(
    use_case: WorkerBeatmapMetadataFetch,
    target: BeatmapFetchTarget,
    semaphore: asyncio.Semaphore | None,
) -> None:
    """Configured semaphoreがあればmetadata fetch同時実行数を制限する.

    Args:
        use_case (WorkerBeatmapMetadataFetch): 実行するmetadata fetch use-case.
        target (BeatmapFetchTarget): metadata fetch対象.
        semaphore (asyncio.Semaphore | None): 同時実行数制限. 未設定なら制限しない.

    Returns:
        None: use-case実行を完了する.
    """
    if semaphore is None:
        await use_case.execute(target)
        return
    async with semaphore:
        await use_case.execute(target)


@jobs.register(task_name="fetch_beatmap_metadata")
async def fetch_beatmap_metadata(
    target_type: str,
    target_key: str,
    context: Annotated[Context, TaskiqDepends()],
    *,
    force_refresh: bool = False,
    direct_point_lookup: bool = False,
) -> None:
    """Taskiq payload から beatmap metadata fetch command を呼び出す.

    Args:
        target_type (str): metadata fetch の target 種別を表す primitive payload.
        target_key (str): target 種別に対応する lookup key.
        context (Context): use-case を取得する Taskiq runtime context.
        force_refresh (bool): cache 状態にかかわらず refresh するか.
        direct_point_lookup (bool): stable direct point lookup由来のmetadata取得か.

    Returns:
        None: typed target を use-case へ委譲して完了する.

    Raises:
        RuntimeError: metadata fetch use-case が worker state に未登録の場合.
        ValueError: payload が BeatmapFetchTarget の不変条件を満たさない場合.
    """
    use_case = get_beatmap_metadata_fetch(context.state)
    if use_case is None:
        logger.error(
            "beatmap_metadata_fetch_runtime_unavailable",
            task_name="fetch_beatmap_metadata",
            target_type=target_type,
            target_key=target_key,
        )
        msg = "beatmap metadata fetch use-case is not registered"
        raise RuntimeError(msg)
    target = BeatmapFetchTarget.from_queue_payload(
        target_type=target_type,
        target_key=target_key,
        force_refresh=force_refresh,
    )
    semaphore = get_beatmap_metadata_fetch_semaphore(context.state)
    if direct_point_lookup:
        scheduler = get_osu_direct_catalog_scheduler(context.state)
        if scheduler is None:
            logger.error(
                "osu_direct_catalog_scheduler_runtime_unavailable",
                task_name="fetch_beatmap_metadata",
                target_type=target_type,
                target_key=target_key,
            )
            msg = "osu!direct catalog scheduler is not registered"
            raise RuntimeError(msg)

        async def work() -> None:
            """Metadata fetch use-caseをscheduler内で実行する.

            Returns:
                None: use-caseへtargetを渡して完了する.
            """
            await _run_metadata_fetch(use_case, target, semaphore)

        _ = await scheduler.run(DirectCatalogWorkKind.POINT_LOOKUP, work)
        return

    await _run_metadata_fetch(use_case, target, semaphore)


@jobs.register(task_name="fetch_beatmap_file")
async def fetch_beatmap_file(
    target_type: str,
    target_key: str,
    context: Annotated[Context, TaskiqDepends()],
    *,
    force_refresh: bool = False,
) -> None:
    """Taskiq payload から beatmap file fetch command を呼び出す.

    Args:
        target_type (str): file fetch の target 種別を表す primitive payload.
        target_key (str): target 種別に対応する lookup key.
        context (Context): use-case を取得する Taskiq runtime context.
        force_refresh (bool): cache 状態にかかわらず refresh するか.

    Returns:
        None: typed target を use-case へ委譲して完了する.

    Raises:
        RuntimeError: file fetch use-case が worker state に未登録の場合.
        ValueError: payload が BeatmapFetchTarget の不変条件を満たさない場合.
    """
    use_case = get_beatmap_file_fetch(context.state)
    if use_case is None:
        logger.error(
            "beatmap_file_fetch_runtime_unavailable",
            task_name="fetch_beatmap_file",
            target_type=target_type,
            target_key=target_key,
        )
        msg = "beatmap file fetch use-case is not registered"
        raise RuntimeError(msg)
    target = BeatmapFetchTarget.from_queue_payload(
        target_type=target_type,
        target_key=target_key,
        force_refresh=force_refresh,
    )
    await use_case.execute(target)


__all__ = [
    "WorkerBeatmapFileFetch",
    "WorkerBeatmapMetadataFetch",
    "WorkerDirectCatalogScheduler",
    "fetch_beatmap_file",
    "fetch_beatmap_metadata",
    "get_beatmap_file_fetch",
    "get_beatmap_metadata_fetch",
    "get_beatmap_metadata_fetch_semaphore",
    "get_osu_direct_catalog_scheduler",
]
