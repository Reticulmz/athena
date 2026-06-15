"""Composition tests for beatmap mirror provider wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from tests.factories.config import make_app_config

from osu_server.composition.providers.app import enqueue_beatmap_fetch
from osu_server.composition.providers.container import make_app_container
from osu_server.composition.providers.test import make_in_memory_runtime_provider_set
from osu_server.domain.beatmaps import (
    BeatmapFileProvider,
    BeatmapFreshnessPolicy,
    BeatmapMetadataProvider,
)
from osu_server.repositories.interfaces.beatmap_repository import (
    BeatmapFetchTarget,
    BeatmapRepository,
)
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository
from osu_server.services.beatmap_mirror import (
    BeatmapEligibilityService,
    BeatmapFileProviderService,
    BeatmapMirrorService,
)

if TYPE_CHECKING:
    from pathlib import Path

    from taskiq import AsyncBroker


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


@pytest.mark.asyncio
async def test_beatmap_mirror_dependencies_resolve_from_app_container(
    tmp_path: Path,
) -> None:
    config = make_app_config(
        environment="test",
        blob_storage_local_root=str(tmp_path / "blobs"),
    )
    container = make_app_container(
        config,
        overrides=(make_in_memory_runtime_provider_set(blob_root=tmp_path / "blobs"),),
    )

    try:
        assert isinstance(await container.get(BeatmapRepository), InMemoryBeatmapRepository)
        assert isinstance(await container.get(BeatmapMirrorService), BeatmapMirrorService)
        assert isinstance(await container.get(BeatmapMetadataProvider), BeatmapMetadataProvider)
        assert isinstance(await container.get(BeatmapFileProvider), BeatmapFileProviderService)
        assert isinstance(
            await container.get(BeatmapEligibilityService),
            BeatmapEligibilityService,
        )
        assert isinstance(await container.get(BeatmapFreshnessPolicy), BeatmapFreshnessPolicy)
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_beatmap_fetch_enqueue_routes_metadata_targets_to_metadata_job() -> None:
    broker = _FakeBroker()

    await enqueue_beatmap_fetch(
        cast("AsyncBroker", cast("object", broker)),
        BeatmapFetchTarget.metadata_by_checksum("0123456789abcdef0123456789abcdef"),
    )

    assert broker.metadata.calls == [
        ("metadata:checksum", "0123456789abcdef0123456789abcdef"),
    ]
    assert broker.file.calls == []


@pytest.mark.asyncio
async def test_beatmap_fetch_enqueue_routes_file_targets_to_file_job() -> None:
    broker = _FakeBroker()

    await enqueue_beatmap_fetch(
        cast("AsyncBroker", cast("object", broker)),
        BeatmapFetchTarget.file_by_beatmap_id(1),
    )

    assert broker.metadata.calls == []
    assert broker.file.calls == [("file:beatmap", "1")]
