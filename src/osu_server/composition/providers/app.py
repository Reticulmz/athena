"""App process provider set."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from dishka import Provider, Scope


@dataclass(frozen=True, slots=True)
class AppProviderGraph:
    """Marker resolved from the app dependency graph."""

    name: str = "app"


@final
class AppProviderSet(Provider):
    """Providers owned by the app process graph."""

    def __init__(self) -> None:
        super().__init__(scope=Scope.APP)
        _ = self.provide(
            self.app_provider_graph,
            provides=AppProviderGraph,
            scope=Scope.APP,
        )

    def app_provider_graph(self) -> AppProviderGraph:
        return AppProviderGraph()
