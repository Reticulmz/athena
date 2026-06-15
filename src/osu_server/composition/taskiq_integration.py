"""Taskiq integration helpers for the Dishka worker container."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dishka.integrations.taskiq import ContainerMiddleware, setup_dishka

if TYPE_CHECKING:
    from dishka import AsyncContainer
    from taskiq import AsyncBroker


def setup_taskiq_dishka(container: AsyncContainer, broker: AsyncBroker) -> None:
    """Install one Dishka middleware instance on the taskiq broker."""
    broker.middlewares = [
        middleware
        for middleware in broker.middlewares
        if not isinstance(middleware, ContainerMiddleware)
    ]
    setup_dishka(container=container, broker=broker)
