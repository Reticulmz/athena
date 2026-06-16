"""Provider replacement tests for the Dishka composition surface."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from dishka import Scope
from tests.factories.config import make_app_config

from osu_server.composition.providers import __all__ as provider_exports
from osu_server.composition.providers import app as app_providers
from osu_server.composition.providers import beatmaps as beatmap_providers
from osu_server.composition.providers import beatmaps_app as beatmap_app_providers
from osu_server.composition.providers import chat as chat_providers
from osu_server.composition.providers import chat_app as chat_app_providers
from osu_server.composition.providers import container as container_providers
from osu_server.composition.providers import identity as identity_providers
from osu_server.composition.providers import infrastructure as infrastructure_providers
from osu_server.composition.providers import performance as performance_providers
from osu_server.composition.providers import performance_cli as performance_cli_providers
from osu_server.composition.providers import repositories as repository_providers
from osu_server.composition.providers import score_submission as score_submission_providers
from osu_server.composition.providers import scores as score_providers
from osu_server.composition.providers import stable_bancho as stable_bancho_providers
from osu_server.composition.providers import stable_web_legacy as stable_web_legacy_providers
from osu_server.composition.providers import storage as storage_providers
from osu_server.composition.providers import worker as worker_providers
from osu_server.composition.providers.app import AppProviderGraph
from osu_server.composition.providers.container import make_app_container, make_worker_container
from osu_server.composition.providers.test import TestProviderSet, replace_value
from osu_server.composition.providers.worker import WorkerProviderGraph
from osu_server.config import AppConfig
from osu_server.infrastructure.messaging.local import LocalEventBus
from osu_server.infrastructure.messaging.memory import InMemoryLocalEventBus
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.memory.session_store import InMemorySessionStore

PRODUCTION_PROVIDER_MODULES = (
    infrastructure_providers,
    repository_providers,
    performance_providers,
    performance_cli_providers,
    storage_providers,
    beatmap_providers,
    chat_providers,
    score_providers,
    app_providers,
    identity_providers,
    chat_app_providers,
    beatmap_app_providers,
    score_submission_providers,
    stable_bancho_providers,
    stable_web_legacy_providers,
    worker_providers,
    container_providers,
)

SOURCE_ROOT = Path(__file__).parents[3] / "src" / "osu_server"


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
    event_bus: LocalEventBus = InMemoryLocalEventBus()
    packet_queue: PacketQueue = InMemoryPacketQueue(max_size=1)

    container = make_worker_container(
        config,
        overrides=(
            TestProviderSet(
                replace_value(LocalEventBus, event_bus, scope=Scope.APP),
                replace_value(PacketQueue, packet_queue, scope=Scope.APP),
            ),
        ),
    )

    try:
        resolved_config = await container.get(AppConfig)
        resolved_graph = await container.get(WorkerProviderGraph)
        resolved_event_bus = await container.get(LocalEventBus)
        resolved_queue = await container.get(PacketQueue)

        assert resolved_config.environment == "production"
        assert resolved_graph.name == "worker"
        assert resolved_event_bus is event_bus
        assert resolved_queue is packet_queue
    finally:
        await container.close()


def test_production_provider_modules_do_not_branch_on_test_environment() -> None:
    for module in PRODUCTION_PROVIDER_MODULES:
        source = inspect.getsource(module)
        assert 'environment == "test"' not in source
        assert "environment == 'test'" not in source


def test_provider_package_exports_modular_sets_without_common_provider() -> None:
    assert "CommonProviderSet" not in provider_exports
    assert "InfrastructureProviderSet" in provider_exports
    assert "PerformanceCliProviderSet" in provider_exports
    assert "PerformanceProviderSet" in provider_exports
    assert "RepositoryProviderSet" in provider_exports
    assert "StableWebLegacyProviderSet" in provider_exports


def test_app_and_worker_provider_sets_are_marker_only() -> None:
    assert _provider_method_names(app_providers.AppProviderSet) == ("app_provider_graph",)
    assert _provider_method_names(worker_providers.WorkerProviderSet) == ("worker_provider_graph",)


def test_production_provider_modules_use_decorator_first_registration() -> None:
    for module in PRODUCTION_PROVIDER_MODULES:
        if module is container_providers:
            continue

        source = inspect.getsource(module)
        assert "for source, provides in" not in source
        assert ".provide(" not in source


def test_provider_definitions_stay_out_of_domain_and_infrastructure_packages() -> None:
    for package_path in (SOURCE_ROOT / "domain", SOURCE_ROOT / "infrastructure"):
        for source_path in package_path.rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))

            assert not _imports_dishka(tree), source_path
            assert not _contains_provider_subclass(tree), source_path


def _provider_method_names(provider_type: type[object]) -> tuple[str, ...]:
    return tuple(
        name for name in provider_type.__dict__ if not name.startswith("_") and name != "scope"
    )


def _imports_dishka(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == "dishka" or alias.name.startswith("dishka.") for alias in node.names
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (node.module == "dishka" or node.module.startswith("dishka."))
        ):
            return True
    return False


def _contains_provider_subclass(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "Provider":
                return True
            if isinstance(base, ast.Attribute) and base.attr == "Provider":
                return True
    return False
