"""Taskiq integration helpers for the Dishka worker container."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from dishka import Provider, Scope
from dishka.integrations.taskiq import ContainerMiddleware, setup_dishka

from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
)
from osu_server.services.commands.chat import (
    PersistChannelMessageUseCase,
    PersistPrivateMessageUseCase,
)

if TYPE_CHECKING:
    from dishka import AsyncContainer
    from taskiq import AsyncBroker


@dataclass(frozen=True, slots=True)
class WorkerRuntimeUseCases:
    """Worker task use-cases built during startup and exposed through Dishka."""

    persist_channel_message: PersistChannelMessageUseCase
    persist_private_message: PersistPrivateMessageUseCase
    fetch_beatmap_metadata: FetchBeatmapMetadataUseCase
    fetch_beatmap_file: FetchBeatmapFileUseCase


@final
class WorkerRuntimeProviderSet(Provider):
    """Provider set for startup-built worker task use-cases."""

    def __init__(self, use_cases: WorkerRuntimeUseCases) -> None:
        super().__init__(scope=Scope.APP)
        self._use_cases = use_cases

        for source, provides in (
            (self.persist_channel_message, PersistChannelMessageUseCase),
            (self.persist_private_message, PersistPrivateMessageUseCase),
            (self.fetch_beatmap_metadata, FetchBeatmapMetadataUseCase),
            (self.fetch_beatmap_file, FetchBeatmapFileUseCase),
        ):
            _ = self.provide(source, provides=provides, scope=Scope.APP, override=True)

    def persist_channel_message(self) -> PersistChannelMessageUseCase:
        return self._use_cases.persist_channel_message

    def persist_private_message(self) -> PersistPrivateMessageUseCase:
        return self._use_cases.persist_private_message

    def fetch_beatmap_metadata(self) -> FetchBeatmapMetadataUseCase:
        return self._use_cases.fetch_beatmap_metadata

    def fetch_beatmap_file(self) -> FetchBeatmapFileUseCase:
        return self._use_cases.fetch_beatmap_file


def setup_taskiq_dishka(container: AsyncContainer, broker: AsyncBroker) -> None:
    """Install one Dishka middleware instance on the taskiq broker."""
    broker.middlewares = [
        middleware
        for middleware in broker.middlewares
        if not isinstance(middleware, ContainerMiddleware)
    ]
    setup_dishka(container=container, broker=broker)
