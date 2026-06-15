"""Worker process provider set."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide


@dataclass(frozen=True, slots=True)
class WorkerProviderGraph:
    """Marker resolved from the worker dependency graph."""

    name: str = "worker"


@final
class WorkerProviderSet(Provider):
    """Marker provider for the worker process graph."""

    scope = Scope.APP

    @provide
    def worker_provider_graph(self) -> WorkerProviderGraph:
        return WorkerProviderGraph()
