"""app processの依存graphを識別するproviderを提供する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide


@dataclass(frozen=True, slots=True)
class AppProviderGraph:
    """app dependency graphから解決されるmarkerを表す.

    Attributes:
        name (str): app process用graphであることを示す固定名.
    """

    name: str = "app"


@final
class AppProviderSet(Provider):
    """app process専用のmarkerをAPP scopeで登録するprovider set.

    Attributes:
        scope (Scope): container全体で共有するDishkaのAPP scope.
    """

    scope = Scope.APP

    @provide
    def app_provider_graph(self) -> AppProviderGraph:
        """App processのcompositionを識別するmarkerを生成する.

        Returns:
            AppProviderGraph: app graph用の固定marker.
        """
        return AppProviderGraph()
