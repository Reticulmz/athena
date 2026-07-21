"""beatmap fetch command use-case を呼び出す Taskiq adapter を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol, cast

import structlog
from taskiq import Context, TaskiqDepends

from osu_server.domain.beatmaps import BeatmapFetchTarget
from osu_server.infrastructure.jobs.registry import jobs

if TYPE_CHECKING:
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

        Raises:
            Exception: use-case の処理に失敗した場合.
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

        Raises:
            Exception: use-case の処理に失敗した場合.
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


@jobs.register(task_name="fetch_beatmap_metadata")
async def fetch_beatmap_metadata(
    target_type: str,
    target_key: str,
    context: Annotated[Context, TaskiqDepends()],
    *,
    force_refresh: bool = False,
) -> None:
    """Taskiq payload から beatmap metadata fetch command を呼び出す.

    Args:
        target_type (str): metadata fetch の target 種別を表す primitive payload.
        target_key (str): target 種別に対応する lookup key.
        context (Context): use-case を取得する Taskiq runtime context.
        force_refresh (bool): cache 状態にかかわらず refresh するか.

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
    await use_case.execute(target)


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
    "fetch_beatmap_file",
    "fetch_beatmap_metadata",
    "get_beatmap_file_fetch",
    "get_beatmap_metadata_fetch",
]
