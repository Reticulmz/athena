"""Common provider set shared by app and worker dependency graphs."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.config import AppConfig
from osu_server.infrastructure.messaging.interfaces import EventBus
from osu_server.infrastructure.messaging.memory import InMemoryEventBus
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue


@final
class CommonProviderSet(Provider):
    """Common providers that have no process-specific ownership."""

    def __init__(self, config: AppConfig) -> None:
        super().__init__(scope=Scope.APP)
        self._config: AppConfig = config
        _ = self.provide(self.config, provides=AppConfig, scope=Scope.APP)
        _ = self.provide(self.event_bus, provides=EventBus, scope=Scope.APP)
        _ = self.provide(self.packet_queue, provides=PacketQueue, scope=Scope.APP)

    def config(self) -> AppConfig:
        return self._config

    def event_bus(self) -> EventBus:
        return InMemoryEventBus()

    def packet_queue(self, config: AppConfig) -> PacketQueue:
        return InMemoryPacketQueue(max_size=config.packet_queue_max_size)
