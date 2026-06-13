"""Worker process provider set."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from dishka import Provider, Scope


@dataclass(frozen=True, slots=True)
class WorkerProviderGraph:
    """Marker resolved from the worker dependency graph."""

    name: str = "worker"


@final
class WorkerProviderSet(Provider):
    """Providers owned by the worker process graph."""

    def __init__(self) -> None:
        super().__init__(scope=Scope.APP)
        _ = self.provide(
            self.worker_provider_graph,
            provides=WorkerProviderGraph,
            scope=Scope.APP,
        )

    def worker_provider_graph(self) -> WorkerProviderGraph:
        return WorkerProviderGraph()
