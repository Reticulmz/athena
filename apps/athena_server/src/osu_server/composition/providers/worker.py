"""worker process graphを識別するproviderを定義する.

このmoduleはworker containerがapp専用provider群を含まないことを検証可能にするmarkerを提供する.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide


@dataclass(frozen=True, slots=True)
class WorkerProviderGraph:
    """worker dependency graphから解決されるmarkerを表す.

    Attributes:
        name (str): constructorで上書き可能なgraph種別のdefault値worker.
    """

    name: str = "worker"


@final
class WorkerProviderSet(Provider):
    """worker process graphのmarkerを提供する.

    Attributes:
        scope (Scope): worker processの生存期間と一致するDishka scope.
    """

    scope = Scope.APP

    @provide
    def worker_provider_graph(self) -> WorkerProviderGraph:
        """Worker graphであることを表すmarker instanceを提供する.

        Returns:
            WorkerProviderGraph: worker containerから解決可能なgraph marker.
        """
        return WorkerProviderGraph()
