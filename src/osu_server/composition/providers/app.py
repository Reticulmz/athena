"""App process marker provider set."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide


@dataclass(frozen=True, slots=True)
class AppProviderGraph:
    """Marker resolved from the app dependency graph."""

    name: str = "app"


@final
class AppProviderSet(Provider):
    """Marker provider for the app process graph."""

    scope = Scope.APP

    @provide
    def app_provider_graph(self) -> AppProviderGraph:
        return AppProviderGraph()
