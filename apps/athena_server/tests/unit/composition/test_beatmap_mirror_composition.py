"""Beatmap mirror provider wiring の composition 契約を検証する."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, cast

import pytest
from tests.factories.config import make_app_config
from tests.support.beatmaps import InMemoryBeatmapStore

from osu_server.composition.providers.beatmaps_app import (
    BeatmapAppProviderSet,
    enqueue_beatmap_fetch,
)
from osu_server.composition.providers.container import make_app_container
from osu_server.composition.providers.test import make_in_memory_runtime_provider_set
from osu_server.domain.beatmaps import (
    BeatmapFetchTarget,
    BeatmapFileProvider,
    BeatmapFreshnessPolicy,
    BeatmapMetadataProvider,
    DirectPointLookupRequest,
)
from osu_server.infrastructure.beatmaps import BeatmapFileProviderService
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.memory.queries.beatmaps import InMemoryBeatmapQueryRepository
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from taskiq import AsyncBroker

    from osu_server.services.queries.beatmaps.direct_search import DirectPointLookupQuery


class _FakeTask:
    """Taskiq task への enqueue 引数を記録する fake task.

    Attributes:
        calls (list[tuple[str, str]]): target type と key の enqueue 記録.
        force_refresh_calls (list[bool]): force refresh 指定の enqueue 記録.
        direct_point_lookup_calls (list[bool]): direct point lookup指定のenqueue記録.
    """

    def __init__(self) -> None:
        """空の enqueue 記録を持つ fake task を初期化する."""
        self.calls: list[tuple[str, str]] = []
        self.force_refresh_calls: list[bool] = []
        self.direct_point_lookup_calls: list[bool] = []

    async def kiq(
        self,
        target_type: str,
        target_key: str,
        *,
        force_refresh: bool = False,
        direct_point_lookup: bool = False,
    ) -> None:
        """Beatmap fetch job の enqueue 引数を記録する.

        Args:
            target_type (str): fetch 対象種別を表す queue 値.
            target_key (str): fetch 対象を識別する queue 値.
            force_refresh (bool): cache を使わず更新する指定か.
            direct_point_lookup (bool): stable direct point lookup由来のmetadata取得か.

        Returns:
            None: enqueue 引数を記録し, 呼び出し側へ値を返さない.
        """
        self.calls.append((target_type, target_key))
        self.force_refresh_calls.append(force_refresh)
        self.direct_point_lookup_calls.append(direct_point_lookup)


class _FakeBroker:
    """Metadata と file fetch task を名前で返す fake broker.

    Attributes:
        metadata (_FakeTask): metadata fetch task の記録先.
        file (_FakeTask): file fetch task の記録先.
    """

    def __init__(self) -> None:
        """二つの独立した fake task を持つ broker を初期化する."""
        self.metadata: _FakeTask = _FakeTask()
        self.file: _FakeTask = _FakeTask()

    def find_task(self, task_name: str) -> _FakeTask | None:
        """既知の beatmap fetch task 名に対応する fake task を返す.

        Args:
            task_name (str): 検索する Taskiq task 名.

        Returns:
            _FakeTask | None: 対応する task. 未知の名前ではNone.
        """
        if task_name == "fetch_beatmap_metadata":
            return self.metadata
        if task_name == "fetch_beatmap_file":
            return self.file
        return None


@pytest.mark.asyncio
async def test_beatmap_mirror_dependencies_resolve_from_app_container(
    tmp_path: Path,
) -> None:
    """App container が in-memory runtime override 下でbeatmap mirrorの全依存を解決する.

    依存解決の契約を検証する.

    Args:
        tmp_path (Path): test 用 blob storage root を作る一時 directory.

    Returns:
        None: 解決した repository, provider, service の型を検証して完了する.
    """
    config = make_app_config(
        environment="test",
        blob_storage_local_root=str(tmp_path / "blobs"),
    )
    container = make_app_container(
        config,
        overrides=(make_in_memory_runtime_provider_set(blob_root=tmp_path / "blobs"),),
    )

    try:
        assert isinstance(
            await container.get(BeatmapQueryRepository),
            InMemoryBeatmapQueryRepository,
        )
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
    """Metadata target の enqueue が metadata job だけへ target type と key を渡す契約を検証する.

    Returns:
        None: metadata task の記録と file task が未使用なことを検証して完了する.
    """
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
async def test_beatmap_fetch_enqueue_preserves_force_refresh_flag() -> None:
    """Force refresh付きmetadata targetのenqueueがflagをmetadata jobへ保持する.

    この契約を検証する.

    Returns:
        None: target 値, force refresh 記録, file task の未使用を検証して完了する.
    """
    broker = _FakeBroker()

    await enqueue_beatmap_fetch(
        cast("AsyncBroker", cast("object", broker)),
        BeatmapFetchTarget.metadata_by_beatmap_id(1, force_refresh=True),
    )

    assert broker.metadata.calls == [("metadata:beatmap", "1")]
    assert broker.metadata.force_refresh_calls == [True]
    assert broker.file.calls == []


@pytest.mark.asyncio
async def test_beatmap_fetch_enqueue_marks_direct_point_lookup_metadata_targets() -> None:
    """Direct point lookup由来のmetadata enqueueがworker payload flagを保持する.

    Returns:
        None: metadata taskへdirect_point_lookup=Trueが渡ることを検証して完了する.
    """
    broker = _FakeBroker()

    await enqueue_beatmap_fetch(
        cast("AsyncBroker", cast("object", broker)),
        BeatmapFetchTarget.metadata_by_beatmapset_id(1),
        direct_point_lookup=True,
    )

    assert broker.metadata.calls == [("metadata:beatmapset", "1")]
    assert broker.metadata.direct_point_lookup_calls == [True]
    assert broker.file.calls == []


@pytest.mark.asyncio
async def test_direct_point_lookup_query_uses_direct_point_lookup_enqueue() -> None:
    """DirectPointLookupQueryが専用resolverからdirect lookup metadata fetchをenqueueする.

    Returns:
        None: lookup miss時にdirect_point_lookup=True付きmetadata taskが
            enqueueされることを確認する.
    """
    repo = InMemoryBeatmapStore()
    broker = _FakeBroker()
    config = make_app_config(osu_direct_point_lookup_bounded_wait_seconds=0.01)
    provider = BeatmapAppProviderSet()
    build_query = cast(
        "Callable[..., DirectPointLookupQuery]",
        provider.direct_point_lookup_query,
    )
    query = build_query(
        repository=repo.query_repository,
        eligibility_service=BeatmapEligibilityService(),
        freshness_policy=BeatmapFreshnessPolicy(
            ranked_refresh_interval=timedelta(days=30),
            pending_refresh_interval=timedelta(hours=1),
            graveyard_refresh_interval=timedelta(days=30),
            mirror_refresh_interval=timedelta(hours=1),
        ),
        broker=cast("AsyncBroker", cast("object", broker)),
        config=config,
    )

    result = await query.execute(
        DirectPointLookupRequest.beatmapset_id(
            authenticated_user_id=1,
            beatmapset_id=1000,
        )
    )

    assert result.beatmapset is None
    assert broker.metadata.calls == [("metadata:beatmapset", "1000")]
    assert broker.metadata.direct_point_lookup_calls == [True]
    assert broker.file.calls == []


@pytest.mark.asyncio
async def test_beatmap_fetch_enqueue_routes_file_targets_to_file_job() -> None:
    """File target の enqueue が file job だけへ target type と key を渡す契約を検証する.

    Returns:
        None: metadata task の未使用と file task の記録を検証して完了する.
    """
    broker = _FakeBroker()

    await enqueue_beatmap_fetch(
        cast("AsyncBroker", cast("object", broker)),
        BeatmapFetchTarget.file_by_beatmap_id(1),
    )

    assert broker.metadata.calls == []
    assert broker.file.calls == [("file:beatmap", "1")]
