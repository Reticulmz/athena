"""アプリケーション固有の Taskiq job を登録する公開境界を定義する."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from osu_server.infrastructure.jobs.registry import jobs

if TYPE_CHECKING:
    from taskiq import AsyncBroker

_JOB_MODULES = (
    "osu_server.jobs.chat_persistence",
    "osu_server.jobs.beatmap_fetch",
    "osu_server.jobs.osu_direct",
    "osu_server.jobs.score_performance",
    "osu_server.jobs.beatmap_leaderboards",
    "osu_server.jobs.replay_download_accounting",
)


def _load_job_modules() -> None:
    """Job module を import して decorator による registry 登録を行う.

    Returns:
        None: 全 job module の import を完了する.

    Raises:
        ImportError: job module またはその依存先の import に失敗した場合.
    """
    for module_name in _JOB_MODULES:
        _ = import_module(module_name)


def register_all_jobs(broker: AsyncBroker) -> None:
    """登録済みのアプリケーション Taskiq job を broker へ接続する.

    Args:
        broker (AsyncBroker): application job を実行可能にする Taskiq broker.

    Returns:
        None: module import と job 接続を完了する.

    Raises:
        ImportError: job module またはその依存先の import に失敗した場合.
    """
    _load_job_modules()
    jobs.attach_to(broker)


__all__ = ["register_all_jobs"]
