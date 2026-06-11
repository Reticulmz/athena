"""Composition tests for beatmap mirror dependency registration.

Verifies that ``register_services`` wires ``BeatmapMirrorService`` and its
dependency graph correctly in test and non-test environments, with the
expected repository and provider choices for each environment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from osu_server.composition.service_registry import (
    _enqueue_beatmap_fetch,  # pyright: ignore[reportPrivateUsage]
    _register_repositories,  # pyright: ignore[reportPrivateUsage]
    register_services,
)
from osu_server.config import AppConfig
from osu_server.domain.beatmap import (
    BeatmapFileProvider,
    BeatmapFreshnessPolicy,
    BeatmapMetadataProvider,
)
from osu_server.infrastructure.di.container import Container
from osu_server.infrastructure.di.providers import build_container
from osu_server.repositories.interfaces.beatmap_repository import (
    BeatmapFetchTarget,
    BeatmapRepository,
)
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository
from osu_server.repositories.sqlalchemy.beatmap_repository import SQLAlchemyBeatmapRepository
from osu_server.services.beatmap_mirror.file_sources import CompositeBeatmapFileProvider
from osu_server.services.beatmap_mirror_service import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)

if TYPE_CHECKING:
    from taskiq import AsyncBroker


def _make_config(*, environment: str = "test") -> AppConfig:
    return AppConfig.model_validate(
        {
            "database_url": "postgresql://test:test@localhost:5432/test",
            "valkey_url": "redis://localhost:6379/0",
            "environment": environment,
        },
    )


class _FakeTask:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def kiq(self, target_type: str, target_key: str) -> None:
        self.calls.append((target_type, target_key))


class _FakeBroker:
    def __init__(self) -> None:
        self.metadata: _FakeTask = _FakeTask()
        self.file: _FakeTask = _FakeTask()

    def find_task(self, task_name: str) -> _FakeTask | None:
        if task_name == "fetch_beatmap_metadata":
            return self.metadata
        if task_name == "fetch_beatmap_file":
            return self.file
        return None


# ---------------------------------------------------------------------------
# Test environment composition -- full container build + register_services
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_beatmap_mirror_service_resolves_in_test_environment() -> None:
    """BeatmapMirrorService is resolvable with InMemory repository in test env."""
    config = _make_config(environment="test")
    container = await build_container(config)
    await register_services(container, config)

    repo = await container.resolve(BeatmapRepository)
    svc = await container.resolve(BeatmapMirrorService)

    assert isinstance(repo, InMemoryBeatmapRepository)
    assert isinstance(svc, BeatmapMirrorService)


@pytest.mark.asyncio
async def test_beatmap_metadata_provider_resolves_in_test_environment() -> None:
    """BeatmapMetadataProvider composite is resolvable in test environment."""
    config = _make_config(environment="test")
    container = await build_container(config)
    await register_services(container, config)

    provider = await container.resolve(BeatmapMetadataProvider)

    assert isinstance(provider, BeatmapMetadataProvider)


@pytest.mark.asyncio
async def test_beatmap_file_provider_resolves_in_test_environment() -> None:
    """BeatmapFileProvider composite is resolvable in test environment."""
    config = _make_config(environment="test")
    container = await build_container(config)
    await register_services(container, config)

    provider = await container.resolve(BeatmapFileProvider)

    assert isinstance(provider, CompositeBeatmapFileProvider)


@pytest.mark.asyncio
async def test_beatmap_eligibility_service_resolves_in_test_environment() -> None:
    """BeatmapEligibilityService is resolvable in test environment."""
    config = _make_config(environment="test")
    container = await build_container(config)
    await register_services(container, config)

    svc = await container.resolve(BeatmapEligibilityService)

    assert isinstance(svc, BeatmapEligibilityService)


@pytest.mark.asyncio
async def test_beatmap_freshness_policy_resolves_in_test_environment() -> None:
    """BeatmapFreshnessPolicy is resolvable with config-driven intervals."""
    config = _make_config(environment="test")
    container = await build_container(config)
    await register_services(container, config)

    policy = await container.resolve(BeatmapFreshnessPolicy)

    assert isinstance(policy, BeatmapFreshnessPolicy)


@pytest.mark.asyncio
async def test_beatmap_fetch_enqueue_routes_metadata_targets_to_metadata_job() -> None:
    """Metadata fetch targets are sent to the metadata worker task."""
    broker = _FakeBroker()

    await _enqueue_beatmap_fetch(
        cast("AsyncBroker", cast("object", broker)),
        BeatmapFetchTarget.metadata_by_checksum("0123456789abcdef0123456789abcdef"),
    )

    assert broker.metadata.calls == [
        ("metadata:checksum", "0123456789abcdef0123456789abcdef"),
    ]
    assert broker.file.calls == []


@pytest.mark.asyncio
async def test_beatmap_fetch_enqueue_routes_file_targets_to_file_job() -> None:
    """File fetch targets are sent to the file worker task."""
    broker = _FakeBroker()

    await _enqueue_beatmap_fetch(
        cast("AsyncBroker", cast("object", broker)),
        BeatmapFetchTarget.file_by_beatmap_id(1),
    )

    assert broker.metadata.calls == []
    assert broker.file.calls == [("file:beatmap", "1")]


# ---------------------------------------------------------------------------
# Non-test environment -- registration choice verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_development_environment_registers_sqlalchemy_beatmap_repository() -> None:
    """In development, _register_repositories selects SQLAlchemyBeatmapRepository."""
    config = _make_config(environment="development")
    container = Container()
    mock_sf = MagicMock(spec=async_sessionmaker[AsyncSession])

    _register_repositories(container, config, mock_sf)

    repo = await container.resolve(BeatmapRepository)
    assert type(repo) is SQLAlchemyBeatmapRepository


@pytest.mark.asyncio
async def test_test_environment_registers_inmemory_beatmap_repository() -> None:
    """In test, _register_repositories selects InMemoryBeatmapRepository."""
    config = _make_config(environment="test")
    container = Container()
    mock_sf = MagicMock(spec=async_sessionmaker[AsyncSession])

    _register_repositories(container, config, mock_sf)

    repo = await container.resolve(BeatmapRepository)
    assert type(repo) is InMemoryBeatmapRepository
