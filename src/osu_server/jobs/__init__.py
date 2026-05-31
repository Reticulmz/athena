"""Application-specific taskiq job registration boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.infrastructure.jobs.registry import jobs

if TYPE_CHECKING:
    from taskiq import AsyncBroker


def register_all_jobs(broker: AsyncBroker) -> None:
    """Attach registered application taskiq jobs to ``broker``."""
    jobs.attach_to(broker)


__all__ = ["register_all_jobs"]
