"""Application-specific taskiq job registration boundary."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from osu_server.infrastructure.jobs.registry import jobs

if TYPE_CHECKING:
    from taskiq import AsyncBroker

_JOB_MODULES = (
    "osu_server.jobs.chat_persistence",
    "osu_server.jobs.beatmap_fetch",
    "osu_server.jobs.score_performance",
    "osu_server.jobs.beatmap_leaderboards",
    "osu_server.jobs.replay_download_accounting",
)


def _load_job_modules() -> None:
    """Import application job modules so decorators populate the registry."""
    for module_name in _JOB_MODULES:
        _ = import_module(module_name)


def register_all_jobs(broker: AsyncBroker) -> None:
    """Attach registered application taskiq jobs to ``broker``."""
    _load_job_modules()
    jobs.attach_to(broker)


__all__ = ["register_all_jobs"]
