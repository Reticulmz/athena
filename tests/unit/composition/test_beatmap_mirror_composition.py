"""Composition tests for beatmap mirror dependency registration.

Verifies that ``register_services`` wires ``BeatmapMirrorService`` and its
dependency graph correctly in test and non-test environments, with the
expected repository and provider choices for each environment.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from osu_server.composition.service_registry import (
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
from osu_server.repositories.beatmaps.file_sources import CompositeBeatmapFileProvider
from osu_server.repositories.interfaces.beatmap_repository import BeatmapRepository
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository
from osu_server.repositories.sqlalchemy.beatmap_repository import SQLAlchemyBeatmapRepository
from osu_server.services.beatmap_mirror_service import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)


def _make_config(*, environment: str = "test") -> AppConfig:
    return AppConfig.model_validate(
        {
            "database_url": "postgresql://test:test@localhost:5432/test",
            "valkey_url": "redis://localhost:6379/0",
            "environment": environment,
        },
    )


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
