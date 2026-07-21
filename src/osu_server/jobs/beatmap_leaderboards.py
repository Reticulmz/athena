"""Beatmap leaderboard 再構築 command を呼び出す Taskiq adapter を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol, cast, final

import structlog
from taskiq import Context, TaskiqDepends

from osu_server.infrastructure.jobs.registry import jobs
from osu_server.services.commands.scores.leaderboards import (
    RebuildBeatmapLeaderboardsForBeatmapsetCommand,
    RebuildBeatmapLeaderboardsForUserCommand,
    RebuildBeatmapLeaderboardsResult,
)

if TYPE_CHECKING:
    from taskiq import TaskiqState

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))

REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK = "rebuild_beatmap_leaderboards_for_user"
REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK = "rebuild_beatmap_leaderboards_for_beatmapset"


class BeatmapLeaderboardUserRebuildUseCase(Protocol):
    """user 単位の leaderboard 再構築 job が要求する use-case 境界を表す."""

    async def execute(
        self,
        command: RebuildBeatmapLeaderboardsForUserCommand,
    ) -> RebuildBeatmapLeaderboardsResult:
        """User 単位の leaderboard 再構築 command を実行する.

        Args:
            command (RebuildBeatmapLeaderboardsForUserCommand): 再構築対象と理由を持つ command.

        Returns:
            RebuildBeatmapLeaderboardsResult: 対象有無と更新件数を持つ再構築結果.

        Raises:
            Exception: use-case の処理に失敗した場合.
        """
        ...


class BeatmapLeaderboardBeatmapsetRebuildUseCase(Protocol):
    """beatmapset 単位の leaderboard 再構築 job が要求する use-case 境界を表す."""

    async def execute(
        self,
        command: RebuildBeatmapLeaderboardsForBeatmapsetCommand,
    ) -> RebuildBeatmapLeaderboardsResult:
        """Beatmapset 単位の leaderboard 再構築 command を実行する.

        Args:
            command (RebuildBeatmapLeaderboardsForBeatmapsetCommand): 再構築対象と理由を持つ
                command.

        Returns:
            RebuildBeatmapLeaderboardsResult: 対象有無と更新件数を持つ再構築結果.

        Raises:
            Exception: use-case の処理に失敗した場合.
        """
        ...


class _EnqueueableTask(Protocol):
    """primitive payload を enqueue できる Taskiq task の最小境界を表す."""

    async def kiq(self, *args: object, **kwargs: object) -> object:
        """Primitive payload 引数を持つ task を enqueue する.

        Args:
            *args (object): task に渡す positional payload.
            **kwargs (object): task に渡す keyword payload.

        Returns:
            object: broker 実装が返す enqueue 結果.

        Raises:
            Exception: broker 実装が enqueue に失敗した場合.
        """
        ...


class _TaskBroker(Protocol):
    """stable task name から Taskiq task を検索する最小境界を表す."""

    def find_task(self, task_name: str) -> _EnqueueableTask | None:
        """Stable task name で登録済み task を検索する.

        Args:
            task_name (str): Taskiq registry に登録された stable task 名.

        Returns:
            _EnqueueableTask | None: 対応する task または未登録時の None.

        Raises:
            Exception: broker 実装が検索に失敗した場合.
        """
        ...


@final
class TaskiqBeatmapLeaderboardRebuildWorkerWake:
    """leaderboard 再構築の起動要求を Taskiq job へ変換する.

    Attributes:
        _broker (_TaskBroker): task の検索と enqueue を担う broker.
    """

    def __init__(self, broker: _TaskBroker) -> None:
        """Taskiq broker を起動 adapter に設定する.

        Args:
            broker (_TaskBroker): task の検索と enqueue を担う broker.

        Returns:
            None: broker を instance に保持する.
        """
        self._broker = broker

    async def wake_user_rebuild(self, *, user_id: int, reason: str) -> None:
        """User 単位の leaderboard 再構築 task を enqueue する.

        Args:
            user_id (int): 再構築対象 user の ID.
            reason (str): 再構築を要求した理由.

        Returns:
            None: `rebuild_beatmap_leaderboards_for_user` task の enqueue を完了する.

        Raises:
            RuntimeError: 対応する task が broker に未登録の場合.
            Exception: task の検索または enqueue に失敗した場合.
        """
        task_name = REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK
        task = self._broker.find_task(task_name)
        if task is None:
            logger.error(
                "beatmap_leaderboard_rebuild_task_not_registered",
                task_name=task_name,
                target_kind="user",
                user_id=user_id,
                reason=reason,
            )
            msg = "Beatmap Leaderboard user rebuild task is not registered"
            raise RuntimeError(msg)

        try:
            _ = await task.kiq(user_id, reason)
        except Exception:
            logger.exception(
                "beatmap_leaderboard_rebuild_enqueue_failed",
                task_name=task_name,
                target_kind="user",
                user_id=user_id,
                reason=reason,
            )
            raise

    async def wake_beatmapset_rebuild(self, *, beatmapset_id: int, reason: str) -> None:
        """Beatmapset 単位の leaderboard 再構築 task を enqueue する.

        Args:
            beatmapset_id (int): 再構築対象 beatmapset の ID.
            reason (str): 再構築を要求した理由.

        Returns:
            None: `rebuild_beatmap_leaderboards_for_beatmapset` task の enqueue を完了する.

        Raises:
            RuntimeError: 対応する task が broker に未登録の場合.
            Exception: task の検索または enqueue に失敗した場合.
        """
        task_name = REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK
        task = self._broker.find_task(task_name)
        if task is None:
            logger.error(
                "beatmap_leaderboard_rebuild_task_not_registered",
                task_name=task_name,
                target_kind="beatmapset",
                beatmapset_id=beatmapset_id,
                reason=reason,
            )
            msg = "Beatmap Leaderboard beatmapset rebuild task is not registered"
            raise RuntimeError(msg)

        try:
            _ = await task.kiq(beatmapset_id, reason)
        except Exception:
            logger.exception(
                "beatmap_leaderboard_rebuild_enqueue_failed",
                task_name=task_name,
                target_kind="beatmapset",
                beatmapset_id=beatmapset_id,
                reason=reason,
            )
            raise


def get_beatmap_leaderboard_user_rebuild_use_case(
    state: TaskiqState,
) -> BeatmapLeaderboardUserRebuildUseCase | None:
    """Taskiq state から user 単位の leaderboard 再構築 use-case を返す.

    Args:
        state (TaskiqState): worker runtime が保持する Taskiq state.

    Returns:
        BeatmapLeaderboardUserRebuildUseCase | None: 登録済み use-case または未登録時の None.
    """
    return cast(
        "BeatmapLeaderboardUserRebuildUseCase | None",
        getattr(state, "beatmap_leaderboard_user_rebuild_use_case", None),
    )


def get_beatmap_leaderboard_beatmapset_rebuild_use_case(
    state: TaskiqState,
) -> BeatmapLeaderboardBeatmapsetRebuildUseCase | None:
    """Taskiq state から beatmapset 単位の leaderboard 再構築 use-case を返す.

    Args:
        state (TaskiqState): worker runtime が保持する Taskiq state.

    Returns:
        BeatmapLeaderboardBeatmapsetRebuildUseCase | None: 登録済み use-case または未登録時の None.
    """
    return cast(
        "BeatmapLeaderboardBeatmapsetRebuildUseCase | None",
        getattr(state, "beatmap_leaderboard_beatmapset_rebuild_use_case", None),
    )


@jobs.register(task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK)
async def rebuild_beatmap_leaderboards_for_user(
    user_id: object,
    reason: object,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """User 単位の leaderboard 再構築を command use-case に委譲する.

    Args:
        user_id (object): 正の整数でなければならない再構築対象 user の ID.
        reason (object): 空文字列でない再構築要求理由.
        context (Context): use-case を取得する Taskiq runtime context.

    Returns:
        None: `rebuild_beatmap_leaderboards_for_user` の実行と完了ログを記録する.

    Raises:
        ValueError: user_id または reason が task payload の制約を満たさない場合.
        RuntimeError: user 単位の再構築 use-case が worker state に未登録の場合.

    Notes:
        task name と primitive payload の順序は worker の互換 contract として維持する.
    """
    validated_user_id = _validate_positive_int(user_id, "user_id")
    validated_reason = _validate_non_empty_str(reason, "reason")
    use_case = get_beatmap_leaderboard_user_rebuild_use_case(context.state)
    if use_case is None:
        logger.error(
            "beatmap_leaderboard_rebuild_runtime_unavailable",
            task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK,
            target_kind="user",
            user_id=validated_user_id,
        )
        msg = "Beatmap Leaderboard user rebuild use-case is not registered"
        raise RuntimeError(msg)

    logger.info(
        "beatmap_leaderboard_rebuild_requested",
        task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK,
        target_kind="user",
        user_id=validated_user_id,
        reason=validated_reason,
    )
    result = await use_case.execute(
        RebuildBeatmapLeaderboardsForUserCommand(
            user_id=validated_user_id,
            reason=validated_reason,
        )
    )
    _log_completed(
        task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK,
        target_kind="user",
        reason=validated_reason,
        result=result,
        user_id=validated_user_id,
    )


@jobs.register(task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK)
async def rebuild_beatmap_leaderboards_for_beatmapset(
    beatmapset_id: object,
    reason: object,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Beatmapset 単位の leaderboard 再構築を command use-case に委譲する.

    Args:
        beatmapset_id (object): 正の整数でなければならない再構築対象 beatmapset の ID.
        reason (object): 空文字列でない再構築要求理由.
        context (Context): use-case を取得する Taskiq runtime context.

    Returns:
        None: `rebuild_beatmap_leaderboards_for_beatmapset` の実行と完了ログを記録する.

    Raises:
        ValueError: beatmapset_id または reason が task payload の制約を満たさない場合.
        RuntimeError: beatmapset 単位の再構築 use-case が worker state に未登録の場合.

    Notes:
        task name と primitive payload の順序は worker の互換 contract として維持する.
    """
    validated_beatmapset_id = _validate_positive_int(beatmapset_id, "beatmapset_id")
    validated_reason = _validate_non_empty_str(reason, "reason")
    use_case = get_beatmap_leaderboard_beatmapset_rebuild_use_case(context.state)
    if use_case is None:
        logger.error(
            "beatmap_leaderboard_rebuild_runtime_unavailable",
            task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK,
            target_kind="beatmapset",
            beatmapset_id=validated_beatmapset_id,
        )
        msg = "Beatmap Leaderboard beatmapset rebuild use-case is not registered"
        raise RuntimeError(msg)

    logger.info(
        "beatmap_leaderboard_rebuild_requested",
        task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK,
        target_kind="beatmapset",
        beatmapset_id=validated_beatmapset_id,
        reason=validated_reason,
    )
    result = await use_case.execute(
        RebuildBeatmapLeaderboardsForBeatmapsetCommand(
            beatmapset_id=validated_beatmapset_id,
            reason=validated_reason,
        )
    )
    _log_completed(
        task_name=REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK,
        target_kind="beatmapset",
        reason=validated_reason,
        result=result,
        beatmapset_id=validated_beatmapset_id,
    )


def _validate_positive_int(value: object, field_name: str) -> int:
    """Task payload の値が bool ではない正の整数か検証する.

    Args:
        value (object): 検証する primitive payload.
        field_name (str): error message に含める payload field 名.

    Returns:
        int: 検証済みの正の整数.

    Raises:
        ValueError: value が bool または正の整数以外の場合.
    """
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        msg = f"{field_name} must be a positive integer"
        raise ValueError(msg)
    return value


def _validate_non_empty_str(value: object, field_name: str) -> str:
    """Task payload の値が空文字列でない文字列か検証する.

    Args:
        value (object): 検証する primitive payload.
        field_name (str): error message に含める payload field 名.

    Returns:
        str: 検証済みの空文字列でない文字列.

    Raises:
        ValueError: value が文字列でないか空文字列の場合.
    """
    if not isinstance(value, str) or not value:
        msg = f"{field_name} must be a non-empty string"
        raise ValueError(msg)
    return value


def _log_completed(
    *,
    task_name: str,
    target_kind: str,
    reason: str,
    result: RebuildBeatmapLeaderboardsResult,
    user_id: int | None = None,
    beatmapset_id: int | None = None,
) -> None:
    """Leaderboard 再構築の完了結果を構造化ログへ記録する.

    Args:
        task_name (str): 完了した stable Taskiq task 名.
        target_kind (str): `user` または `beatmapset` を表す対象種別.
        reason (str): 再構築を要求した理由.
        result (RebuildBeatmapLeaderboardsResult): 対象有無と更新件数を持つ処理結果.
        user_id (int | None): user 対象時の ID. beatmapset 対象時は None.
        beatmapset_id (int | None): beatmapset 対象時の ID. user 対象時は None.

    Returns:
        None: 完了 event を構造化ログへ記録する.

    Notes:
        user_id と beatmapset_id のうち対象に対応する一方だけを設定する.
    """
    logger.info(
        "beatmap_leaderboard_rebuild_completed",
        task_name=task_name,
        target_kind=target_kind,
        user_id=user_id,
        beatmapset_id=beatmapset_id,
        reason=reason,
        target_found=result.target_found,
        source_score_count=result.source_score_count,
        projection_row_count=result.projection_row_count,
    )


__all__ = [
    "REBUILD_BEATMAP_LEADERBOARDS_FOR_BEATMAPSET_TASK",
    "REBUILD_BEATMAP_LEADERBOARDS_FOR_USER_TASK",
    "BeatmapLeaderboardBeatmapsetRebuildUseCase",
    "BeatmapLeaderboardUserRebuildUseCase",
    "TaskiqBeatmapLeaderboardRebuildWorkerWake",
    "get_beatmap_leaderboard_beatmapset_rebuild_use_case",
    "get_beatmap_leaderboard_user_rebuild_use_case",
    "rebuild_beatmap_leaderboards_for_beatmapset",
    "rebuild_beatmap_leaderboards_for_user",
]
