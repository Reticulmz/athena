"""Provider replacement tests for the Dishka composition surface."""

from __future__ import annotations

import inspect

import pytest
from dishka import Scope
from tests.factories.config import make_app_config

from osu_server.composition.providers import app as app_providers
from osu_server.composition.providers import common as common_providers
from osu_server.composition.providers import container as container_providers
from osu_server.composition.providers import worker as worker_providers
from osu_server.composition.providers.app import AppProviderGraph
from osu_server.composition.providers.container import make_app_container, make_worker_container
from osu_server.composition.providers.test import TestProviderSet, replace_value
from osu_server.composition.providers.worker import WorkerProviderGraph
from osu_server.config import AppConfig
from osu_server.infrastructure.messaging.interfaces import EventBus
from osu_server.infrastructure.messaging.memory import InMemoryEventBus
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.memory.session_store import InMemorySessionStore


@pytest.mark.asyncio
async def test_app_container_accepts_test_provider_replacements_without_test_env() -> None:
    config = make_app_config(environment="development")
    packet_queue: PacketQueue = InMemoryPacketQueue(max_size=2)
    session_store: SessionStore = InMemorySessionStore()

    container = make_app_container(
        config,
        overrides=(
            TestProviderSet(
                replace_value(PacketQueue, packet_queue, scope=Scope.APP),
                replace_value(SessionStore, session_store, scope=Scope.APP),
            ),
        ),
    )

    try:
        resolved_config = await container.get(AppConfig)
        resolved_graph = await container.get(AppProviderGraph)
        resolved_queue = await container.get(PacketQueue)
        resolved_sessions = await container.get(SessionStore)

        assert resolved_config.environment == "development"
        assert resolved_graph.name == "app"
        assert resolved_queue is packet_queue
        assert resolved_sessions is session_store

        await resolved_queue.refresh_ttl(user_id=1, ttl=60)
        await resolved_queue.enqueue(1, b"first", b"second", b"third")
        assert await resolved_queue.dequeue_all(1) == b"secondthird"
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_worker_container_accepts_test_provider_replacements_without_test_env() -> None:
    config = make_app_config(environment="production")
    event_bus: EventBus = InMemoryEventBus()
    packet_queue: PacketQueue = InMemoryPacketQueue(max_size=1)

    container = make_worker_container(
        config,
        overrides=(
            TestProviderSet(
                replace_value(EventBus, event_bus, scope=Scope.APP),
                replace_value(PacketQueue, packet_queue, scope=Scope.APP),
            ),
        ),
    )

    try:
        resolved_config = await container.get(AppConfig)
        resolved_graph = await container.get(WorkerProviderGraph)
        resolved_event_bus = await container.get(EventBus)
        resolved_queue = await container.get(PacketQueue)

        assert resolved_config.environment == "production"
        assert resolved_graph.name == "worker"
        assert resolved_event_bus is event_bus
        assert resolved_queue is packet_queue
    finally:
        await container.close()


def test_production_provider_modules_do_not_branch_on_test_environment() -> None:
    production_modules = (
        common_providers,
        app_providers,
        worker_providers,
        container_providers,
    )

    for module in production_modules:
        source = inspect.getsource(module)
        assert 'environment == "test"' not in source
        assert "environment == 'test'" not in source
